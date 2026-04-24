import asyncio
import logging

import qbittorrentapi
import torrentool.api as torrentool

from config import Configuration


class BittorrentAPI:
    """Async wrapper around qBittorrentAPI for managing torrent downloads."""

    def __init__(self, config: Configuration) -> None:
        self.qbittorrent_host = config.qbittorrent_host
        self.qbittorrent_port = config.qbittorrent_port
        self.qbittorrent_username = config.qbittorrent_username
        self.qbittorrent_password = config.qbittorrent_password
        self.config = config
        self.stop_event = asyncio.Event()
        self.logger = logging.getLogger(__name__)

    POLL_INTERVAL = 3
    DONE_STATES = {"uploading", "stalledUP", "pausedUP", "queuedUP", "forcedUP"}

    async def torrent_task(self, torrent_path: str, symlink_paths: list[str]) -> str:
        """Add a torrent, wait for it to complete, and return the save_path."""
        loop = asyncio.get_running_loop()

        # ── Connect ───────────────────────────────────────────────────────────
        def connect() -> qbittorrentapi.Client:
            client = qbittorrentapi.Client(
                host=self.qbittorrent_host,
                port=self.qbittorrent_port,
                username=self.qbittorrent_username,
                password=self.qbittorrent_password,
            )
            client.auth_log_in()
            return client

        def set_eta_checkpoint_placeholders(seconds: int, symlink_paths: list[str]) -> str:
            """Return a checkpoint label based on ETA."""
            if seconds < 0 or seconds == 8640000:
                return "⬛ No estimate (stalled or no peers)"

            minutes = seconds / 60

            for symlink in symlink_paths:
                if symlink.is_symlink():
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
                    symlink.symlink_to(self.config.placeholder_less_then_five_min_left_path)

        client = await loop.run_in_executor(None, connect)
        self.logger.info("Connected to qBittorrent %s", client.app.version)

        # ── Read hash from .torrent file ──────────────────────────────────────
        torrent_info = torrentool.Torrent.from_file(torrent_path)
        torrent_hash = torrent_info.info_hash.lower()
        self.logger.info("Torrent hash: %s", torrent_hash)

        # ── Add torrent ───────────────────────────────────────────────────────
        await loop.run_in_executor(
            None,
            lambda: client.torrents_add(torrent_files=torrent_path),
        )
        self.logger.info("Torrent added")

        # ── Wait for metadata ─────────────────────────────────────────────────
        self.logger.info("Waiting for metadata…")
        while True:
            torrents = await loop.run_in_executor(
                None, lambda: client.torrents_info(torrent_hashes=torrent_hash)
            )
            if torrents and torrents[0].state not in ("metaDL", "checkingResumeData"):
                break
            await asyncio.sleep(1)

        # ── Progress loop ─────────────────────────────────────────────────────
        t = None
        while True:
            results = await loop.run_in_executor(
                None, lambda: client.torrents_info(torrent_hashes=torrent_hash)
            )

            if not results:
                await asyncio.sleep(self.POLL_INTERVAL)
                continue

            t = results[0]
            pct      = t.progress * 100
            speed_mb = t.dlspeed / 1e6
            eta_s    = t.get("eta", -1)
            eta_str  = f"{eta_s // 60}m {eta_s % 60}s" if eta_s >= 0 else "unknown"

            set_eta_checkpoint_placeholders(eta_s, symlink_paths)

            self.logger.info(
                "%5.1f%%  |  %6.2f MB/s  |  ETA %s  |  seeds %s  peers %s",
                pct, speed_mb, eta_str, t.num_seeds, t.num_leechs,
            )

            if t.state in self.DONE_STATES or t.progress >= 1.0:
                break

            await asyncio.sleep(self.POLL_INTERVAL)

        # ── Done ──────────────────────────────────────────────────────────────
        self.stop_event.set()

        self.logger.info("Download complete!")
        if t:
            self.logger.info("Name: %s", t.name)
            self.logger.info("Size: %.2f GB", t.size / 1e9)
            self.logger.info("Saved: %s", t.save_path)
            return t.save_path
        return ""