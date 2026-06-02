import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Optional

from config import Configuration
from jellyfin_api.jellyfin_api import JellyfinApi
from jellyfin_api.bittorrentapi import BittorrentAPI, SPEED_UNLIMITED, SPEED_20_MBPS, SPEED_5_MBPS
from models.torrent import Torrent
from models.local_file_information import LocalFileInformation
from models.show_season import ShowSeason

IMDB_PATH_PATTERN = re.compile(r"\[imdbid-(tt\d+)\]")
IMDB_URL_PATTERN = re.compile(r"tt\d+")

def extract_imdb_id(path: str) -> Optional[str]:
    """Extract IMDb ID from a Jellyfin media path.

    e.g. '/media/movies/My Movie [imdbid=tt123456567]/MyMovie.mkv' → 'tt123456567'
    """
    match = IMDB_PATH_PATTERN.search(path)
    return match.group(1) if match else None

def extract_imdb_id_from_url(path: str) -> Optional[str]:
    """Extract IMDb ID from a Jellyfin media path.

    e.g. 'https://www.imdb.com/title/tt0257290/?ref_=fn_t_1' → 'tt0257290'
    """
    match = IMDB_URL_PATTERN.search(path)
    return match.group(0) if match else None


@dataclass
class MediaDownloadRequest:
    """Represents a user's request to play a specific episode."""
    imdb_id: str
    played_path: str
    jellyfin_item_id: str
    torrent: Torrent
    local_info: LocalFileInformation
    episode_file_index: int  # index within the original_file_path semicolon list
    show_season: Optional[ShowSeason] = None


class TorrentSyncService:
    """Async service: polls Jellyfin and downloads torrents with priority-based throttling.

    Download priority:
      1. Selected episode → full speed (unlimited)
      2. Rest of season → 20 Mbps
      3. Rest of show (other seasons) → 5 Mbps

    If a new episode is selected during season/show download, it interrupts and
    prioritizes the new episode at full speed.
    """

    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.jellyfin = JellyfinApi(config)
        self.bittorrent = BittorrentAPI(config)
        self.logger = config.get_logger(__name__)

        # Set of (jellyfin_item_id, episode_file_index) tuples currently queued or downloading.
        # Prevents re-queuing the same playback on every 1-second Jellyfin poll.
        self._inflight_keys: set[tuple[str, int]] = set()
        self._media_download_queue: asyncio.Queue[MediaDownloadRequest] = asyncio.Queue()
        self._interrupt_event: asyncio.Event = asyncio.Event()
        self._current_request: Optional[MediaDownloadRequest] = None

    # ── Jellyfin polling task ─────────────────────────────────────────────────

    async def _poll_jellyfin(self) -> None:
        loop = asyncio.get_running_loop()

        self.logger.info("Jellyfin poller started (server: %s)", self.jellyfin.server_url)

        while True:
            newly_played = await loop.run_in_executor(
                None, self.jellyfin.fetch_items,
            )

            if newly_played:
                for item in newly_played:
                    await self._process_played_item(item)

            await asyncio.sleep(1)

    # ── Process a played item into a download request ─────────────────────────

    async def _process_played_item(self, item: dict) -> None:
        now_playing = item.get('NowPlayingItem', {})
        path = now_playing.get('Path')

        if path is None:
            return

        imdb_id = extract_imdb_id(path)

        if not imdb_id:
            self.logger.warning("No IMDb ID in path for %s", path)
            return

        loop = asyncio.get_running_loop()

        torrent: Optional[Torrent] = await loop.run_in_executor(
            None, self.config.torrent_repository.find_registered_media_by_imdb_id, imdb_id,
        )
        if not torrent:
            self.logger.warning("No torrent in DB for IMDb ID %s", imdb_id)
            return

        local_info: Optional[LocalFileInformation] = await loop.run_in_executor(
            None, lambda: self.config.local_files_repository.find_first_by(torrent_id=torrent.id),
        )
        if not local_info or not local_info.torrent_file_local_path:
            self.logger.warning("No local torrent file found for torrent %s", torrent.title)
            return

        episode_file_index = self._find_episode_index(path, local_info)
        jellyfin_item_id = now_playing.get('Id', '')
        key = (jellyfin_item_id, episode_file_index)

        # Jellyfin sessions return the same NowPlayingItem on every poll while
        # playback continues; skip if we've already queued or are downloading it.
        if key in self._inflight_keys:
            return

        # If a show download is currently running and a newer playback request
        # arrives, interrupt the running phase so the new request can take over.
        current = self._current_request
        if current is not None and current.torrent.is_show:
            current_key = (current.jellyfin_item_id, current.episode_file_index)
            if current_key != key:
                self.logger.info("New playback requested — interrupting current show download")
                self._interrupt_event.set()

        show_season: Optional[ShowSeason] = await loop.run_in_executor(
            None, lambda: self.config.show_season_repository.find_first_by(torrent_id=torrent.id),
        )

        self.logger.info("Played: %s (IMDb: %s)", path, imdb_id)

        request = MediaDownloadRequest(
            imdb_id=imdb_id,
            played_path=path,
            jellyfin_item_id=jellyfin_item_id,
            torrent=torrent,
            local_info=local_info,
            episode_file_index=episode_file_index,
            show_season=show_season,
        )

        self._inflight_keys.add(key)
        await self._media_download_queue.put(request)

    def _find_episode_index(self, played_path: str, local_info: LocalFileInformation) -> int:
        """Find which file index in the torrent corresponds to the played path."""
        symlink_paths = local_info.symlink_path.split(";")

        for i, symlink_path in enumerate(symlink_paths):
            if symlink_path.strip() == played_path.strip():
                return i

        # Fallback: try partial match (filename only)
        played_filename = Path(played_path).name
        for i, symlink_path in enumerate(symlink_paths):
            if Path(symlink_path.strip()).name == played_filename:
                return i

        self.logger.warning("Could not match played path to episode index, defaulting to 0")
        return 0

    # ── Download orchestrator ─────────────────────────────────────────────────

    async def _download_orchestrator(self) -> None:
        """Main download loop that processes episode requests with priority."""
        self.logger.info("Download orchestrator started")

        while True:
            request = await self._media_download_queue.get()
            self._current_request = request
            self._interrupt_event.clear()

            try:
                if request.torrent.is_show:
                    await self._handle_show_download(request)
                else:
                    await self._handle_movie_download(request)
            except Exception as exc:
                self.logger.error("Download failed for %s: %s", request.torrent.title, exc)
            finally:
                self._current_request = None
                self._inflight_keys.discard((request.jellyfin_item_id, request.episode_file_index))

    # ── Movie download (simple, no prioritization) ────────────────────────────

    async def _handle_movie_download(self, request: MediaDownloadRequest) -> None:
        self.logger.info("Starting movie download: %s", request.torrent.title)

        save_path = await self.bittorrent.torrent_task(
            request.local_info.torrent_file_local_path,
            request.local_info.symlink_path.split(";"),
        )

        if save_path:
            self._update_symlinks(request.local_info, save_path)
            self.logger.info("Triggering Jellyfin to scan the new item")
            self.jellyfin.refresh_item(request.jellyfin_item_id)
            self.logger.info("Movie download complete: %s", request.torrent.title)

    # ── TV Show download (3-phase with priority) ──────────────────────────────

    async def _handle_show_download(self, request: MediaDownloadRequest) -> None:
        self.logger.info(
            "Starting show download: %s (episode index: %d)",
            request.torrent.title, request.episode_file_index,
        )

        # Phase 1: Download the selected episode at full speed
        completed = await self._phase_episode(request)
        if not completed:
            return  # Interrupted, new request will take over

        # Phase 2: Download the rest of the season at 20 Mbps
        completed = await self._phase_season(request)
        if not completed:
            return  # Interrupted

        # Phase 3: Download other seasons of the show at 5 Mbps
        await self._phase_show(request)

    async def _phase_episode(self, request: MediaDownloadRequest) -> bool:
        """Phase 1: Download only the selected episode at full speed."""
        self.logger.info("Phase 1: Downloading episode at full speed")

        torrent_hash = await self.bittorrent.add_torrent(request.local_info.torrent_file_local_path)
        torrent_files = await self.bittorrent.get_torrent_files(torrent_hash)

        # Match the episode file to the qBittorrent file index
        original_files = request.local_info.original_file_path.split(";")
        target_original_file = original_files[request.episode_file_index].strip()

        qbt_file_index = self._find_qbt_file_index(torrent_files, target_original_file)
        if qbt_file_index is None:
            self.logger.error("Could not find episode file '%s' in torrent files", target_original_file)
            return True  # Don't block, move to next phase

        # Set all files to "do not download", then enable only the target episode
        all_indices = [f["index"] for f in torrent_files]
        await self.bittorrent.set_file_priorities(torrent_hash, all_indices, 0)
        await self.bittorrent.set_file_priorities(torrent_hash, [qbt_file_index], 7)

        # Full speed
        await self.bittorrent.set_download_limit(torrent_hash, SPEED_UNLIMITED)

        # Wait for the episode to download
        symlink_paths = request.local_info.symlink_path.split(";")
        episode_symlink = symlink_paths[request.episode_file_index].strip()

        completed = await self.bittorrent.wait_for_files_complete(
            torrent_hash,
            [qbt_file_index],
            symlink_paths=[episode_symlink],
            interrupt_event=self._interrupt_event,
        )

        if completed:
            # Update symlink for the downloaded episode
            save_path = await self.bittorrent.get_save_path(torrent_hash)
            if save_path:
                self._update_single_symlink(
                    save_path, target_original_file,
                    symlink_paths[request.episode_file_index].strip(),
                )
            self.logger.info("Episode download complete, refreshing Jellyfin")
            self.jellyfin.refresh_item(request.jellyfin_item_id)
            return True

        return False

    async def _phase_season(self, request: MediaDownloadRequest) -> bool:
        """Phase 2: Download the rest of the season at 20 Mbps."""
        self.logger.info("Phase 2: Downloading rest of season at 20 Mbps")

        torrent_hash = await self.bittorrent.add_torrent(request.local_info.torrent_file_local_path)
        torrent_files = await self.bittorrent.get_torrent_files(torrent_hash)

        season_positions = self._get_target_season_positions(
            request.local_info,
            request.episode_file_index,
        )

        original_files = request.local_info.original_file_path.split(";")
        season_qbt_indices: list[int] = []
        for pos in season_positions:
            if pos >= len(original_files):
                continue
            original_file = original_files[pos].strip()
            qbt_index = self._find_qbt_file_index(torrent_files, original_file)
            if qbt_index is not None:
                season_qbt_indices.append(qbt_index)

        season_qbt_indices = list(dict.fromkeys(season_qbt_indices))

        if not season_qbt_indices:
            self.logger.error("Could not resolve season files in torrent for phase 2")
            return False

        # Download only target season files in this torrent.
        all_indices = [f["index"] for f in torrent_files]
        await self.bittorrent.set_file_priorities(torrent_hash, all_indices, 0)
        await self.bittorrent.set_file_priorities(torrent_hash, season_qbt_indices, 1)

        # Throttle to 20 Mbps
        await self.bittorrent.set_download_limit(torrent_hash, SPEED_20_MBPS)

        # Wait for target season files to complete
        symlink_paths = request.local_info.symlink_path.split(";")
        season_symlinks = [symlink_paths[pos].strip() for pos in season_positions if pos < len(symlink_paths)]
        completed = await self.bittorrent.wait_for_files_complete(
            torrent_hash,
            season_qbt_indices,
            symlink_paths=season_symlinks,
            interrupt_event=self._interrupt_event,
        )

        if completed:
            save_path = await self.bittorrent.get_save_path(torrent_hash)
            if save_path:
                self._update_selected_symlinks(request.local_info, save_path, season_positions)
            self.logger.info("Season download complete")
            self.jellyfin.refresh_item(request.jellyfin_item_id)
            return True

        return False

    async def _phase_show(self, request: MediaDownloadRequest) -> None:
        """Phase 3: Download other seasons of the show at 5 Mbps."""
        if not request.show_season:
            self.logger.info("No show_season info, skipping phase 3")
            return

        loop = asyncio.get_running_loop()
        show_id = request.show_season.show_id

        # Find all other seasons for this show
        all_seasons: list[ShowSeason] = await loop.run_in_executor(
            None, self.config.show_season_repository.get_all_seasons_for_show, show_id,
        )

        other_seasons = [s for s in all_seasons if s.torrent_id != request.torrent.id]

        if not other_seasons:
            self.logger.info("No other seasons to download for show %s", show_id)
            return

        self.logger.info("Phase 3: Downloading %d other season(s) at 5 Mbps", len(other_seasons))

        for season in other_seasons:
            if self._interrupt_event.is_set():
                self.logger.info("Phase 3 interrupted")
                return

            season_torrent: Optional[Torrent] = await loop.run_in_executor(
                None, self.config.torrent_repository.get, season.torrent_id,
            )
            if not season_torrent:
                continue

            season_local_info: Optional[LocalFileInformation] = await loop.run_in_executor(
                None, lambda: self.config.local_files_repository.find_first_by(torrent_id=season.torrent_id),
            )
            if not season_local_info or not season_local_info.torrent_file_local_path:
                continue

            self.logger.info("Downloading season %d-%d: %s", season.season, season.season_to, season_torrent.title)

            torrent_hash = await self.bittorrent.add_torrent(season_local_info.torrent_file_local_path)

            # Enable all files, throttle to 5 Mbps
            torrent_files = await self.bittorrent.get_torrent_files(torrent_hash)
            all_indices = [f["index"] for f in torrent_files]
            await self.bittorrent.set_file_priorities(torrent_hash, all_indices, 1)
            await self.bittorrent.set_download_limit(torrent_hash, SPEED_5_MBPS)

            symlink_paths = season_local_info.symlink_path.split(";")
            completed = await self.bittorrent.wait_for_torrent_complete(
                torrent_hash,
                symlink_paths=symlink_paths,
                interrupt_event=self._interrupt_event,
            )

            if completed:
                save_path = await self.bittorrent.get_save_path(torrent_hash)
                if save_path:
                    self._update_symlinks(season_local_info, save_path)
                self.logger.info("Season %d-%d download complete", season.season, season.season_to)
            else:
                self.logger.info("Phase 3 interrupted during season %d", season.season)
                return

        self.logger.info("All seasons downloaded for show %s", show_id)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_qbt_file_index(self, torrent_files: list[dict], original_file: str) -> Optional[int]:
        """Find the qBittorrent file index matching the original file path."""
        original_filename = Path(original_file).name

        # Try exact path match first
        for f in torrent_files:
            if f["name"] == original_file or f["name"].endswith("/" + original_file):
                return f["index"]

        # Fallback: match by filename
        for f in torrent_files:
            if Path(f["name"]).name == original_filename:
                return f["index"]

        return None

    def _update_single_symlink(self, save_path: str, original_file: str, symlink_str: str) -> None:
        """Update a single symlink to point to the downloaded file."""
        save_path = save_path.replace(self.config.downloaded_directory, self.config.downloaded_target_directory)
        downloaded_file = Path(save_path) / original_file
        symlink = Path(symlink_str)

        if not downloaded_file.exists():
            self.logger.warning("Downloaded file not found: %s", downloaded_file)
            return

        if symlink.is_symlink():
            symlink.unlink()

        symlink.symlink_to(downloaded_file)
        self.logger.info("Symlink updated: %s → %s", symlink, downloaded_file)

    def _update_symlinks(self, local_info: LocalFileInformation, save_path: str) -> None:
        """Update all symlinks to point to downloaded files."""
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
            self._update_single_symlink(save_path, original_file.strip(), symlink_str.strip())

    def _update_selected_symlinks(
        self,
        local_info: LocalFileInformation,
        save_path: str,
        selected_positions: list[int],
    ) -> None:
        """Update only selected symlinks by semicolon-list positions."""
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

        for pos in selected_positions:
            if pos < 0 or pos >= len(symlink_paths):
                continue
            self._update_single_symlink(
                save_path,
                original_files[pos].strip(),
                symlink_paths[pos].strip(),
            )

    def _get_target_season_positions(
        self,
        local_info: LocalFileInformation,
        episode_file_index: int,
    ) -> list[int]:
        """Return semicolon-list positions that belong to the played season."""
        symlink_paths = [p.strip() for p in local_info.symlink_path.split(";")]

        if not symlink_paths:
            return [episode_file_index]

        if episode_file_index < 0 or episode_file_index >= len(symlink_paths):
            return [0]

        target_parent = Path(symlink_paths[episode_file_index]).parent
        positions = [
            i for i, symlink_path in enumerate(symlink_paths)
            if Path(symlink_path).parent == target_parent
        ]

        return positions if positions else [episode_file_index]

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the Jellyfin polling loop and download orchestrator."""
        await asyncio.gather(
            self._poll_jellyfin(),
            self._download_orchestrator(),
        )
