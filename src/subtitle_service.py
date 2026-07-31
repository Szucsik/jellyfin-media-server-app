"""Downloads Hungarian subtitles for English media via Jellyfin's Open Subtitles plugin.

Flow:
  1. Query the database for every English (``language == "ENG"``) movie and
     show-season torrent that is registered as playable media.
  2. Map those records to concrete Jellyfin items (movies and episodes) by
     matching their IMDb id against Jellyfin's ``ProviderIds``.
  3. For each item, download a Hungarian subtitle through the Open Subtitles
     plugin, skipping items that already have one and respecting the provider's
     per-day download limit.
"""
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from config import Configuration
from jellyfin_api.jellyfin_api import JellyfinApi
from models.subtitle_download import SubtitleDownload

IMDB_ID_PATTERN = re.compile(r"tt\d+")


def extract_imdb_id(text: Optional[str]) -> Optional[str]:
    """Extract an IMDb id (e.g. 'tt0257290') from a URL or arbitrary string."""
    if not text:
        return None
    match = IMDB_ID_PATTERN.search(text)
    return match.group(0) if match else None


class SubtitleUpdateService:
    """Fetches Hungarian subtitles for English movies and episodes."""

    # Terminal statuses that mean an item already has (or was resolved for) a subtitle.
    _RESOLVED_STATUSES = frozenset({"downloaded", "already_present"})

    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.jellyfin = JellyfinApi(config)
        self.logger = config.get_logger(__name__)

        self.source_language = config.subtitle_source_language
        self.target_language = config.subtitle_target_language
        self.daily_limit = config.subtitle_daily_limit

        self.torrent_repository = config.torrent_repository
        self.subtitle_repository = config.subtitle_download_repository

        self.logger.info(
            "SubtitleUpdateService initialised (source_language=%s, target_language=%s, daily_limit=%d)",
            self.source_language, self.target_language, self.daily_limit,
        )

    # ── Public entry point ────────────────────────────────────────────────────
    def run(self, stop_event: Optional[threading.Event] = None) -> dict:
        """Process every English item and download missing Hungarian subtitles.

        Returns a stats dict summarising the run.
        """
        stats = {
            "processed": 0,
            "downloaded": 0,
            "already_present": 0,
            "not_found": 0,
            "failed": 0,
            "skipped": 0,
            "limit_reached": False,
        }

        self.logger.info("%s Subtitle run starting %s", "=" * 20, "=" * 20)

        window_start = datetime.utcnow() - timedelta(days=1)
        already_downloaded = self.subtitle_repository.count_downloaded_since(window_start)
        remaining = self.daily_limit - already_downloaded

        self.logger.info(
            "Subtitle run: %d download(s) already used in the last 24h (since %s), %d remaining",
            already_downloaded, window_start.isoformat(), remaining,
        )

        if remaining <= 0:
            self.logger.warning(
                "Daily subtitle download limit (%d) already exhausted; nothing to do",
                self.daily_limit,
            )
            stats["limit_reached"] = True
            self.logger.info("Subtitle run finished: %s", stats)
            return stats

        candidates = self._collect_candidates()
        self.logger.info("Resolved %d Jellyfin item(s) to check for subtitles", len(candidates))

        for index, (item, imdb_id, torrent_id) in enumerate(candidates, start=1):
            if stop_event is not None and stop_event.is_set():
                self.logger.info("Subtitle run stopped by request after %d item(s)", index - 1)
                break

            self.logger.debug(
                "Processing candidate %d/%d: item_id=%s name=%r imdb=%s torrent_id=%s (remaining=%d)",
                index, len(candidates), item.get("Id"), item.get("Name", ""),
                imdb_id, torrent_id, remaining,
            )

            outcome = self._process_item(item, imdb_id, torrent_id, can_download=remaining > 0)

            if outcome == "limit_reached":
                stats["limit_reached"] = True
                self.logger.warning(
                    "Daily subtitle download limit reached at candidate %d/%d; stopping run",
                    index, len(candidates),
                )
                break

            stats["processed"] += 1
            stats[outcome] += 1
            if outcome == "downloaded":
                remaining -= 1
                self.logger.debug("Download budget remaining: %d", remaining)

        self.logger.info("%s Subtitle run finished: %s %s", "=" * 20, stats, "=" * 20)
        return stats

    # ── Candidate resolution ──────────────────────────────────────────────────
    def _collect_candidates(self) -> list[tuple[dict, str, Optional[int]]]:
        """Resolve every English DB record to a Jellyfin (item, imdb_id, torrent_id) triple."""
        self.logger.info("Collecting candidates: fetching Jellyfin library items")
        movies = self.jellyfin.fetch_library_items("Movie")
        series = self.jellyfin.fetch_library_items("Series")
        self.logger.info(
            "Fetched %d Jellyfin movie(s) and %d series from the library",
            len(movies), len(series),
        )
        movie_by_imdb = self._index_by_imdb(movies)
        series_by_imdb = self._index_by_imdb(series)
        self.logger.debug(
            "Indexed %d movie(s) and %d series by IMDb id",
            len(movie_by_imdb), len(series_by_imdb),
        )

        candidates: list[tuple[dict, str, Optional[int]]] = []
        seen_item_ids: set[str] = set()

        # English movies
        english_movies = self.torrent_repository.find_movies_by_language(self.source_language)
        self.logger.info(
            "Found %d %s movie torrent(s) in the database",
            len(english_movies), self.source_language,
        )
        for torrent in english_movies:
            imdb_id = extract_imdb_id(torrent.imdb_link)
            if not imdb_id:
                self.logger.warning(
                    "Skipping movie torrent %s: no IMDb id in imdb_link %r",
                    torrent.id, torrent.imdb_link,
                )
                continue
            item = movie_by_imdb.get(imdb_id)
            if item is None:
                self.logger.warning("No Jellyfin movie found for IMDb %s (torrent %s)", imdb_id, torrent.id)
                continue
            item_id = item.get("Id")
            if not item_id or item_id in seen_item_ids:
                self.logger.debug("Skipping duplicate/empty movie item_id=%s (imdb=%s)", item_id, imdb_id)
                continue
            seen_item_ids.add(item_id)
            self.logger.debug(
                "Movie candidate: item_id=%s name=%r imdb=%s torrent_id=%s",
                item_id, item.get("Name", ""), imdb_id, torrent.id,
            )
            candidates.append((item, imdb_id, torrent.id))

        self.logger.info("Movie candidates resolved: %d", len(candidates))

        # English show seasons → collect the eligible season numbers per series.
        # A series' episodes may come from several season torrents, so map each
        # season number back to the torrent that provides it.
        english_seasons = self.torrent_repository.find_show_seasons_by_language(self.source_language)
        self.logger.info(
            "Found %d %s show-season torrent(s) in the database",
            len(english_seasons), self.source_language,
        )
        allowed_seasons: dict[str, set[int]] = defaultdict(set)
        season_torrent_ids: dict[str, dict[int, Optional[int]]] = defaultdict(dict)
        for torrent, show_season in english_seasons:
            imdb_id = extract_imdb_id(torrent.imdb_link)
            if not imdb_id:
                self.logger.warning(
                    "Skipping show-season torrent %s: no IMDb id in imdb_link %r",
                    torrent.id, torrent.imdb_link,
                )
                continue
            season_numbers = self._season_numbers(show_season.season, show_season.season_to)
            allowed_seasons[imdb_id] |= season_numbers
            for season_number in season_numbers:
                season_torrent_ids[imdb_id].setdefault(season_number, torrent.id)
            self.logger.debug(
                "Show-season torrent %s (imdb=%s) covers seasons %s",
                torrent.id, imdb_id, sorted(season_numbers),
            )

        episode_candidate_count = 0
        for imdb_id, seasons in allowed_seasons.items():
            series_item = series_by_imdb.get(imdb_id)
            if series_item is None:
                self.logger.warning("No Jellyfin series found for IMDb %s", imdb_id)
                continue
            series_id = series_item["Id"]
            self.logger.debug(
                "Fetching episodes for series %s (imdb=%s), eligible seasons=%s",
                series_id, imdb_id, sorted(seasons),
            )
            episodes = self.jellyfin.fetch_series_episodes(series_id)
            self.logger.debug("Series %s returned %d episode(s)", series_id, len(episodes))
            for episode in episodes:
                season_number = episode.get("ParentIndexNumber")
                if season_number not in seasons:
                    continue
                item_id = episode.get("Id")
                if not item_id or item_id in seen_item_ids:
                    self.logger.debug("Skipping duplicate/empty episode item_id=%s (imdb=%s)", item_id, imdb_id)
                    continue
                seen_item_ids.add(item_id)
                torrent_id = season_torrent_ids[imdb_id].get(season_number)
                self.logger.debug(
                    "Episode candidate: item_id=%s name=%r imdb=%s season=%s torrent_id=%s",
                    item_id, episode.get("Name", ""), imdb_id, season_number, torrent_id,
                )
                candidates.append((episode, imdb_id, torrent_id))
                episode_candidate_count += 1

        self.logger.info(
            "Candidate resolution complete: %d episode candidate(s), %d total candidate(s)",
            episode_candidate_count, len(candidates),
        )
        return candidates

    @staticmethod
    def _index_by_imdb(items: list[dict]) -> dict[str, dict]:
        """Map IMDb id → first Jellyfin item carrying that provider id."""
        index: dict[str, dict] = {}
        for item in items:
            imdb_id = (item.get("ProviderIds") or {}).get("Imdb")
            if imdb_id:
                index.setdefault(imdb_id, item)
        return index

    @staticmethod
    def _season_numbers(season: int, season_to: int) -> set[int]:
        """Expand a season range into the set of season numbers it covers."""
        if season is None or season < 0:
            return set()
        if season_to is None or season_to < season:
            return {season}
        return set(range(season, season_to + 1))

    # ── Per-item processing ───────────────────────────────────────────────────
    def _process_item(
        self, item: dict, imdb_id: str, torrent_id: Optional[int], can_download: bool
    ) -> str:
        """Download a subtitle for a single Jellyfin item.

        Returns one of: downloaded / already_present / not_found / failed /
        skipped / limit_reached.
        """
        item_id = item.get("Id")
        name = item.get("Name", "")

        existing = self.subtitle_repository.get_by_item_id(item_id)
        if existing is not None and existing.status in self._RESOLVED_STATUSES:
            self.logger.info(
                "Skipping '%s' (item_id=%s): already resolved with status '%s'",
                name, item_id, existing.status,
            )
            return "skipped"

        if JellyfinApi.item_has_subtitle_language(item, self.target_language):
            self.logger.info(
                "Item '%s' (item_id=%s) already has a %s subtitle stream; recording as already_present",
                name, item_id, self.target_language,
            )
            self._record(item_id, imdb_id, torrent_id, name, "already_present", downloaded=True)
            return "already_present"

        # From here on a fresh download would be required.
        if not can_download:
            self.logger.warning(
                "Cannot download subtitle for '%s' (item_id=%s): daily limit budget exhausted",
                name, item_id,
            )
            return "limit_reached"

        self.logger.info(
            "Searching %s subtitles for '%s' (item_id=%s, imdb=%s)",
            self.target_language, name, item_id, imdb_id,
        )
        results = self.jellyfin.search_remote_subtitles(item_id, self.target_language)
        self.logger.info("Subtitle search for '%s' returned %d result(s)", name, len(results))
        if not results:
            self.logger.info("No %s subtitle found for '%s' (item_id=%s)", self.target_language, name, item_id)
            self._record(item_id, imdb_id, torrent_id, name, "not_found")
            return "not_found"

        best = self._pick_best(results)
        self.logger.info(
            "Downloading subtitle %s (provider=%s, downloads=%s) for '%s' (item_id=%s)",
            best.get("Id"), best.get("ProviderName"), best.get("DownloadCount"), name, item_id,
        )
        if self.jellyfin.download_remote_subtitle(item_id, best["Id"]):
            self.logger.info("Downloaded %s subtitle for '%s'", self.target_language, name)
            self._record(item_id, imdb_id, torrent_id, name, "downloaded", downloaded=True)
            return "downloaded"

        self.logger.error(
            "Subtitle download failed for '%s' (item_id=%s, subtitle=%s)",
            name, item_id, best.get("Id"),
        )
        self._record(item_id, imdb_id, torrent_id, name, "failed")
        return "failed"

    @staticmethod
    def _pick_best(results: list[dict]) -> dict:
        """Pick the most trustworthy subtitle: hash match, then popularity, then rating."""
        def sort_key(result: dict) -> tuple:
            return (
                1 if result.get("IsHashMatch") else 0,
                result.get("DownloadCount") or 0,
                result.get("CommunityRating") or 0.0,
            )

        return max(results, key=sort_key)

    def _record(
        self,
        item_id: str,
        imdb_id: str,
        torrent_id: Optional[int],
        name: str,
        status: str,
        downloaded: bool = False,
    ) -> None:
        """Persist the outcome for an item so future runs can skip / count it."""
        self.logger.debug(
            "Recording subtitle outcome: item_id=%s torrent_id=%s imdb=%s status=%s downloaded=%s",
            item_id, torrent_id, imdb_id, status, downloaded,
        )
        self.subtitle_repository.upsert(
            SubtitleDownload(
                jellyfin_item_id=item_id,
                torrent_id=torrent_id,
                imdb_id=imdb_id or "",
                name=name,
                language=self.target_language,
                status=status,
                downloaded_at=datetime.utcnow() if downloaded else None,
            )
        )

