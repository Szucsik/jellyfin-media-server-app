import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

import qbittorrentapi
import torrentool.api as torrentool

from config import Configuration

# Speed limits in bytes/sec
SPEED_UNLIMITED = 0
SPEED_160_MBPS = 20_000_000  # 160 Mbit/s
SPEED_20_MBPS = 2_500_000  # 20 Mbit/s


class BittorrentAPI:
    """Async wrapper around qBittorrentAPI for managing torrent downloads."""

    def __init__(self, config: Configuration) -> None:
        self.qbittorrent_host = config.qbittorrent_host
        self.qbittorrent_port = config.qbittorrent_port
        self.qbittorrent_username = config.qbittorrent_username
        self.qbittorrent_password = config.qbittorrent_password
        self.config = config
        self.logger = logging.getLogger(__name__)
        self._client: Optional[qbittorrentapi.Client] = None

    POLL_INTERVAL = 3
    DONE_STATES = {"uploading", "stalledUP", "pausedUP", "queuedUP", "forcedUP"}

    # ── Connection ────────────────────────────────────────────────────────────

    async def connect(self) -> qbittorrentapi.Client:
        """Connect to qBittorrent and return the client."""
        if self._client:
            return self._client

        loop = asyncio.get_running_loop()

        def _connect() -> qbittorrentapi.Client:
            client = qbittorrentapi.Client(
                host=self.qbittorrent_host,
                port=self.qbittorrent_port,
                username=self.qbittorrent_username,
                password=self.qbittorrent_password,
            )
            client.auth_log_in()
            return client

        self._client = await loop.run_in_executor(None, _connect)
        self.logger.info("Connected to qBittorrent %s", self._client.app.version)
        return self._client

    # ── Torrent management ────────────────────────────────────────────────────

    @staticmethod
    def get_torrent_hash(torrent_path: str) -> str:
        """Read the info_hash from a .torrent file."""
        torrent_info = torrentool.Torrent.from_file(torrent_path)
        return torrent_info.info_hash.lower()

    async def add_torrent(self, torrent_path: str) -> str:
        """Add a torrent and wait for metadata. Returns the torrent hash."""
        loop = asyncio.get_running_loop()
        client = await self.connect()
        torrent_hash = self.get_torrent_hash(torrent_path)

        self.logger.info("Torrent hash: %s", torrent_hash)

        # Check if already added
        existing = await loop.run_in_executor(
            None, lambda: client.torrents_info(torrent_hashes=torrent_hash)
        )
        if not existing:
            await loop.run_in_executor(
                None,
                lambda: client.torrents_add(torrent_files=torrent_path),
            )
            self.logger.info("Torrent added: %s", torrent_path)

        # Wait for metadata
        self.logger.info("Waiting for metadata…")
        deadline = asyncio.get_running_loop().time() + 300  # 5 minutes
        while True:
            torrents = await loop.run_in_executor(
                None, lambda: client.torrents_info(torrent_hashes=torrent_hash)
            )
            if torrents and torrents[0].state not in ("metaDL", "checkingResumeData"):
                break
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(f"Timed out waiting for metadata of torrent {torrent_hash}")
            await asyncio.sleep(1)

        return torrent_hash

    async def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        """Get the list of files in a torrent. Each dict has 'name', 'index', 'size', 'progress'."""
        loop = asyncio.get_running_loop()
        client = await self.connect()
        files = await loop.run_in_executor(
            None, lambda: client.torrents_files(torrent_hash=torrent_hash)
        )
        return [
            {"name": f.name, "index": f.index, "size": f.size, "progress": f.progress, "priority": f.priority}
            for f in files
        ]

    async def set_file_priorities(self, torrent_hash: str, file_indices: list[int], priority: int) -> None:
        """Set priority for specific files. Priority: 0=skip, 1=normal, 6=high, 7=max."""
        loop = asyncio.get_running_loop()
        client = await self.connect()
        await loop.run_in_executor(
            None,
            lambda: client.torrents_file_priority(
                torrent_hash=torrent_hash,
                file_ids=file_indices,
                priority=priority,
            ),
        )
        self.logger.info("Set priority %d for files %s in torrent %s", priority, file_indices, torrent_hash[:8])

    async def set_download_limit(self, torrent_hash: str, limit_bytes_per_sec: int) -> None:
        """Set download speed limit for a torrent. 0 = unlimited."""
        loop = asyncio.get_running_loop()
        client = await self.connect()
        await loop.run_in_executor(
            None,
            lambda: client.torrents_set_download_limit(
                limit=limit_bytes_per_sec,
                torrent_hashes=torrent_hash,
            ),
        )
        if limit_bytes_per_sec == 0:
            self.logger.info("Download limit removed for torrent %s", torrent_hash[:8])
        else:
            self.logger.info(
                "Download limit set to %.1f Mbps for torrent %s",
                limit_bytes_per_sec * 8 / 1_000_000,
                torrent_hash[:8],
            )

    async def wait_for_files_complete(
        self,
        torrent_hash: str,
        file_indices: list[int],
        symlink_paths: Optional[list[str]] = None,
        interrupt_event: Optional[asyncio.Event] = None,
        on_placeholder_updated: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Wait until specific files are fully downloaded.

        Returns True if files completed, False if interrupted by interrupt_event.
        """
        loop = asyncio.get_running_loop()
        client = await self.connect()

        while True:
            if interrupt_event and interrupt_event.is_set():
                self.logger.info("Download interrupted for torrent %s", torrent_hash[:8])
                return False

            files = await loop.run_in_executor(
                None, lambda: client.torrents_files(torrent_hash=torrent_hash)
            )

            # Check if all target files are complete
            target_files = [f for f in files if f.index in file_indices]
            all_complete = bool(target_files) and all(f.progress >= 1.0 for f in target_files)

            if all_complete:
                return True

            # Log progress and update placeholders
            total_size = sum(f.size for f in target_files)
            downloaded = sum(f.size * f.progress for f in target_files)
            pct = (downloaded / total_size * 100) if total_size > 0 else 0

            # Get torrent-level info for speed/ETA
            torrents = await loop.run_in_executor(
                None, lambda: client.torrents_info(torrent_hashes=torrent_hash)
            )
            if torrents:
                t = torrents[0]
                speed_mb = t.dlspeed / 1e6
                eta_s = t.get("eta", -1)

                # qBittorrent often reports unknown ETA for selective downloads.
                # Fall back to selected-files remaining bytes / current speed.
                if eta_s < 0 or eta_s == 8640000:
                    if t.dlspeed > 0 and total_size > 0:
                        remaining = max(total_size - downloaded, 0)
                        eta_s = int(remaining / t.dlspeed)

                eta_str = f"{eta_s // 60}m {eta_s % 60}s" if eta_s >= 0 else "unknown"

                self.logger.info(
                    "%5.1f%%  |  %6.2f MB/s  |  ETA %s  |  seeds %s  peers %s",
                    pct, speed_mb, eta_str, t.num_seeds, t.num_leechs,
                )

                if symlink_paths:
                    changed = self._update_eta_placeholders(eta_s, symlink_paths)
                    if changed and on_placeholder_updated:
                        await loop.run_in_executor(None, on_placeholder_updated)
                    self.logger.info("ETA placeholders updated based on torrent-level ETA")
                else:
                    self.logger.info("ETA placeholders not updated because no symlink paths provided")

            await asyncio.sleep(self.POLL_INTERVAL)

    async def wait_for_torrent_complete(
        self,
        torrent_hash: str,
        symlink_paths: Optional[list[str]] = None,
        interrupt_event: Optional[asyncio.Event] = None,
        on_placeholder_updated: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Wait until the entire torrent (all enabled files) is complete.

        Returns True if completed, False if interrupted.
        """
        loop = asyncio.get_running_loop()
        client = await self.connect()

        while True:
            if interrupt_event and interrupt_event.is_set():
                self.logger.info("Download interrupted for torrent %s", torrent_hash[:8])
                return False

            results = await loop.run_in_executor(
                None, lambda: client.torrents_info(torrent_hashes=torrent_hash)
            )

            if not results:
                await asyncio.sleep(self.POLL_INTERVAL)
                continue

            t = results[0]
            pct = t.progress * 100
            speed_mb = t.dlspeed / 1e6
            eta_s = t.get("eta", -1)
            eta_str = f"{eta_s // 60}m {eta_s % 60}s" if eta_s >= 0 else "unknown"

            self.logger.info(
                "%5.1f%%  |  %6.2f MB/s  |  ETA %s  |  seeds %s  peers %s",
                pct, speed_mb, eta_str, t.num_seeds, t.num_leechs,
            )

            if symlink_paths:
                changed = self._update_eta_placeholders(eta_s, symlink_paths)
                if changed and on_placeholder_updated:
                    await loop.run_in_executor(None, on_placeholder_updated)

            # qBittorrent can briefly report a done-like torrent state after a
            # previous selective download. Verify enabled files are complete
            # before we consider the torrent complete.
            files = await loop.run_in_executor(
                None, lambda: client.torrents_files(torrent_hash=torrent_hash)
            )
            enabled_files = [f for f in files if getattr(f, "priority", 1) > 0]

            if enabled_files:
                if all(f.progress >= 1.0 for f in enabled_files):
                    return True
            elif t.state in self.DONE_STATES or t.progress >= 1.0:
                return True

            await asyncio.sleep(self.POLL_INTERVAL)

    async def get_save_path(self, torrent_hash: str) -> str:
        """Get the save path of a torrent."""
        loop = asyncio.get_running_loop()
        client = await self.connect()
        results = await loop.run_in_executor(
            None, lambda: client.torrents_info(torrent_hashes=torrent_hash)
        )
        if results:
            return results[0].save_path
        return ""

    # ── Legacy method (kept for movie downloads) ──────────────────────────────

    async def torrent_task(
        self,
        torrent_path: str,
        symlink_paths: list[str],
        on_placeholder_updated: Optional[Callable[[], None]] = None,
    ) -> str:
        """Add a torrent, wait for it to complete, and return the save_path."""
        torrent_hash = await self.add_torrent(torrent_path)
        completed = await self.wait_for_torrent_complete(
            torrent_hash,
            symlink_paths,
            on_placeholder_updated=on_placeholder_updated,
        )
        if completed:
            save_path = await self.get_save_path(torrent_hash)
            self.logger.info("Download complete! Saved: %s", save_path)
            return save_path
        return ""

    # ── Placeholder helpers ───────────────────────────────────────────────────

    def _update_eta_placeholders(self, seconds: int, symlink_paths: list[str]) -> bool:
        """Update symlinks with ETA-based placeholder files."""
        self.logger.debug("Updating ETA placeholders with %d seconds remaining", seconds)
        
        if seconds < 0 or seconds == 8640000:
            self.logger.info("ETA is unknown, skipping placeholder update")
            return False

        minutes = seconds / 60
        placeholders_dir = self.config.placeholders_directory
        changed = False

        self.logger.debug("Updating placeholder for symlink: %s", symlink_paths)

        for symlink_path in symlink_paths:
            symlink = Path(symlink_path)
            self.logger.debug("Processing symlink: %s", symlink_path)
            if symlink.is_symlink():
                # Never replace a symlink that already points to a real downloaded file.
                current_target = str(symlink.readlink())
                if placeholders_dir not in current_target:
                    self.logger.debug("Symlink %s points to a real file (%s), skipping placeholder update", symlink_path, current_target)
                    continue
                symlink.unlink()
            if minutes >= 60:
                symlink.symlink_to(self.config.placeholder_one_hr_left_path)
            elif minutes > 35:
                symlink.symlink_to(self.config.placeholder_half_hr_left_path)
            elif minutes > 20:
                symlink.symlink_to(self.config.placeholder_less_then_twenty_min_left_path)
            elif minutes > 10:
                symlink.symlink_to(self.config.placeholder_less_then_ten_min_left_path)
            elif minutes > 5:
                symlink.symlink_to(self.config.placeholder_less_then_five_min_left_path)
            else:
                symlink.symlink_to(self.config.placeholder_less_then_a_few_min_left_path)
            changed = True

        return changed