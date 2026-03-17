import asyncio

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
        self.stop_event = asyncio.Event()

    POLL_INTERVAL = 3
    DONE_STATES = {"uploading", "stalledUP", "pausedUP", "queuedUP", "forcedUP"}

    async def torrent_task(self, torrent_path: str) -> str:
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

        client = await loop.run_in_executor(None, connect)
        print("✓ Connected to qBittorrent", client.app.version)

        # ── Read hash from .torrent file ──────────────────────────────────────
        torrent_info = torrentool.Torrent.from_file(torrent_path)
        torrent_hash = torrent_info.info_hash.lower()
        print(f"✓ Torrent hash: {torrent_hash}")

        # ── Add torrent ───────────────────────────────────────────────────────
        await loop.run_in_executor(
            None,
            lambda: client.torrents_add(torrent_files=torrent_path),
        )
        print("✓ Torrent added")

        # ── Wait for metadata ─────────────────────────────────────────────────
        print("⏳ Waiting for metadata…")
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
            eta_s    = t.eta
            eta_str  = f"{eta_s // 60}m {eta_s % 60}s" if eta_s >= 0 else "unknown"

            print(
                f"\r  {pct:5.1f}%  |  {speed_mb:6.2f} MB/s  |  "
                f"ETA {eta_str:>10}  |  seeds {t.num_seeds}  peers {t.num_leechs}   ",
                end="",
                flush=True,
            )

            if t.state in self.DONE_STATES or t.progress >= 1.0:
                break

            await asyncio.sleep(self.POLL_INTERVAL)

        # ── Done ──────────────────────────────────────────────────────────────
        self.stop_event.set()

        print("\n\n✅ Download complete!")
        if t:
            print(f"   Name  : {t.name}")
            print(f"   Size  : {t.size / 1e9:.2f} GB")
            print(f"   Saved : {t.save_path}")
            return t.save_path
        return ""