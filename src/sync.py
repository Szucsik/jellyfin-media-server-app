import asyncio
import os
from pathlib import Path
import re
from typing import Optional

from config import Configuration
from jellyfin_api.jellyfin_api import JellyfinApi
from jellyfin_api.bittorrentapi import BittorrentAPI
from models.torrent import Torrent
from models.local_file_information import LocalFileInformation

IMDB_PATH_PATTERN = re.compile(r"\[imdbid=(tt\d+)\]")


def extract_imdb_id(path: str) -> Optional[str]:
    """Extract IMDb ID from a Jellyfin media path.

    e.g. '/media/movies/My Movie [imdbid=tt123456567]/MyMovie.mkv' → 'tt123456567'
    """
    match = IMDB_PATH_PATTERN.search(path)
    return match.group(1) if match else None


class TorrentSyncService:
    """Async service: polls Jellyfin every second and downloads torrents in parallel."""

    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.jellyfin = JellyfinApi(config)
        self.logger = config.logger

    # ── Jellyfin polling task ─────────────────────────────────────────────────
    async def _poll_jellyfin(self) -> None:
        loop = asyncio.get_running_loop()

        self.logger.info("Jellyfin poller started (server: %s)", self.jellyfin.server_url)

        while True:
            newly_played = await loop.run_in_executor(
                None, self.jellyfin.poll_once,
            )

            if newly_played:
                self.logger.info("🎬 %d item(s) played since last poll", len(newly_played))
                for item in newly_played:
                    asyncio.create_task(self._handle_played_item(item))

            await asyncio.sleep(1)

    # ── Handle a single newly-played item ─────────────────────────────────────
    async def _handle_played_item(self, item: dict) -> None:
        path = item.get("Path", "")
        label = self.jellyfin.item_label(item)
        imdb_id = extract_imdb_id(path)

        if not imdb_id:
            self.logger.warning("No IMDb ID in path for '%s': %s", label, path)
            return

        self.logger.info("Played: %s (IMDb: %s)", label, imdb_id)

        torrent: Optional[Torrent] = self.config.torrent_repository.find_by_imdb_id(imdb_id)
        if not torrent:
            self.logger.warning("No torrent in DB for IMDb ID %s", imdb_id)
            return

        self.logger.info("Starting download: %s", torrent.title)
        try:
            await self._download_torrent(torrent)
            self.logger.info("Download complete: %s", torrent.title)
        except Exception as exc:
            self.logger.error("Download failed for %s: %s", torrent.title, exc)

    # ── Download a single torrent via qBittorrent ─────────────────────────────
    async def _download_torrent(self, torrent: Torrent) -> None:
        loop = asyncio.get_running_loop()

        local_info: Optional[LocalFileInformation] = await loop.run_in_executor(
            None,
            lambda: self.config.local_files_repository.find_first_by(torrent_id=torrent.id),
        )

        if not local_info or not local_info.torrent_file_local_path:
            self.logger.warning("No local torrent file found in DB for torrent %s", torrent.title)
            return

        bittorrent = BittorrentAPI(self.config)
        save_path = await bittorrent.torrent_task(local_info.torrent_file_local_path)

        if save_path:
            await loop.run_in_executor(
                None, self._update_symlinks, local_info, save_path,
            )

    # ── Update symlinks to point to downloaded files ──────────────────────────
    def _update_symlinks(self, local_info: LocalFileInformation, save_path: str) -> None:
        if not local_info.symlink_path or not local_info.original_file_path:
            self.logger.warning("No symlink/original_file_path data for torrent_id %s", local_info.torrent_id)
            return

        symlink_paths = local_info.symlink_path.split(";")
        original_files = local_info.original_file_path.split(";")

        if len(symlink_paths) != len(original_files):
            self.logger.error(
                "Mismatch: %d symlinks vs %d original files for torrent_id %s",
                len(symlink_paths), len(original_files), local_info.torrent_id,
            )
            return

        for symlink_str, original_file in zip(symlink_paths, original_files):
            downloaded_file = Path(save_path) / original_file
            symlink = Path(symlink_str)

            if not downloaded_file.exists():
                self.logger.warning("Downloaded file not found: %s", downloaded_file)
                continue

            if symlink.is_symlink():
                symlink.unlink()

            symlink.symlink_to(downloaded_file)
            self.logger.info("Symlink updated: %s → %s", symlink, downloaded_file)

    # ── Entry point ───────────────────────────────────────────────────────────
    async def run(self) -> None:
        """Start the Jellyfin polling loop (torrent downloads run as parallel tasks)."""
        await self._poll_jellyfin()
