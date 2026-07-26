from config import Configuration
from models.show import Show
from models.torrent import Quality, Torrent
from models.show_season import ShowSeason
from models.movie import Movie

import re


class DataProcessing:
    def __init__(self, config: Configuration):
        self.config = config
        self.logger = config.get_logger(__name__)

    def process(self):
        """Start the data processing for both movies and shows"""
        self.logger.info("Start the data processing for both movies and shows")
        torrents = self.config.torrent_repository.get_all()
        self.logger.info("Torrents collected: %s", len(torrents))

        shows = [t for t in torrents if t.is_show]
        self.logger.info("Shows collected: %s", len(shows))

        movies = [t for t in torrents if not t.is_show]
        self.logger.info("Movies collected: %s", len(movies))

        self._process_movie_torrent_data(movies)
        self._process_show_torrent_data(shows)

    def get_torrent_language(self, torrents: list[Torrent]) -> str:
        """
        Find the main language for the target media file(s).
        Always prioritize Hungarian language.
        """
        language: str = "ENG"
        for t in torrents:
            if t.language == "HUN":
                language = "HUN"
                break

        return language

    def _process_movie_torrent_data(self, torrents: list[Torrent]) -> list[Torrent]:
        """
        Deduplicate torrents that share the same IMDB link, keeping only
        the highest-quality version. Entries with UNASSIGNED quality are
        always discarded when a better-quality duplicate exists.
        """
        self.logger.info("Data processing of the movie data have been started")
        # Build a dict keyed by IMDB link, keeping the best-quality Torrent
        best: dict[str, Torrent] = {}

        order = {
            Quality.HD:         1,   # 720p  – most preferred
            Quality.UHD:        2,   # 1080p
            Quality.SD:         3,   # 2160p
            Quality.UNASSIGNED: 99,  # always last
        }

        for torrent in torrents:
            key = torrent.imdb_link
            existing = best.get(key)

            if existing is None:
                best[key] = torrent
                continue

            # Prefer the torrent with the numerically higher quality value
            if torrent.quality == Quality.UNASSIGNED:
                continue  # Never replace a known-quality entry with an unassigned one

            
            if existing.quality == Quality.UNASSIGNED \
                or torrent.language == "HUN" and existing.language == "ENG"\
                or (torrent.language == existing.language and order.get(torrent.quality) < order.get(existing.quality)):
                
                best[key] = torrent

        for torrent in best.values():
            existing = self.config.movie_repository.find_first_by(torrent_id=torrent.id)
            if existing is None:
                self.config.movie_repository.save(Movie(torrent_id=torrent.id))

    def _process_show_torrent_data(self, torrents: list[Torrent]) -> None:
        """
        For each series (grouped by IMDB link), produce one Torrent per season.
        Preference order:
        1. Single-season torrents over multi-season packs
        2. Higher quality wins (SD=720 < HD=1080 < UHD=2160),
            but prefer lower quality over UNASSIGNED.
        """
        self.logger.info("Data processing of the show data have been started")

        # --- helpers -----------------------------------------------------------

        def quality_rank(t: Torrent) -> int:
            """Lower rank = more preferred (we use min-selection)."""
            order = {
                Quality.SD:         1,   # 720p  – most preferred
                Quality.HD:         2,   # 1080p
                Quality.UHD:        3,   # 2160p
                Quality.UNASSIGNED: 99,  # always last
            }
            return order.get(t.quality, 99)

        def is_single_season(season: int, season_to: int) -> bool:
            return season_to == -1 and season > 0
        
        def is_an_episode(t: Torrent) -> bool:
            match = re.search(r'E(\d+)', t.title)
            return match is not None

        def covers_season(t: ShowSeason, season: int) -> bool:
            """True when this torrent contains the given season number."""
            if is_single_season(t.season, t.season_to):
                return t.season == season
            # multi-season pack: season_from..season_to
            if t.season > 0 and t.season_to > 0:
                return t.season <= season <= t.season_to
            return False
            
        def better(challenger: tuple[Torrent, ShowSeason], current: tuple[Torrent, ShowSeason]) -> bool:
            """
            Returns True if challenger should replace current.
            Single-season always beats multi-season pack.
            Within the same 'tier', lower quality_rank wins.
            """
            challenger_single = is_single_season(challenger[1].season, challenger[1].season_to)
            current_single    = is_single_season(current[1].season, current[1].season_to)

            if challenger_single and not current_single:
                return True   # single-season beats pack
            if not challenger_single and current_single:
                return False  # never replace single with pack

            # same tier → compare quality
            return quality_rank(challenger[0]) < quality_rank(current[0])

        # --- group by series ---------------------------------------------------

        # imdb_link -> list of torrents for that series
        by_series: dict[str, list[Torrent]] = {}
        for torrent in torrents:
            by_series.setdefault(torrent.imdb_link, []).append(torrent)

        # --- pick one torrent per (series, season) -----------------------------

        result: list[Torrent] = []


        # Iterate over each show seasons grouped by IMDB link
        for imdb_link, series_torrents in by_series.items():
            # Find every season number that appears across all torrents
            all_seasons: set[int] = set()

            # We need the Torrent and the Showseason together
            shows: list[tuple[Torrent, ShowSeason]] = []

            # Show season 
            show = self.config.show_repository.find_first_by(imdb_link=imdb_link)
            if show is None:
                show = self.config.show_repository.save(Show(imdb_link=imdb_link))
            show_id = show.id


            # Always prioritize hungarian tv shows
            language: str = self.get_torrent_language(series_torrents)

            for t in series_torrents:
                # Only focus on one language for the entire tv show
                if t.language != language:
                    continue

                show_season = ShowSeason(torrent_id=t.id)

                season_matches = re.findall(r"S(\d{1,2})", t.title)
                episodes = re.findall(r"E(\d{1,2})", t.title)

                if len(season_matches) == 0:
                    continue

                if is_an_episode(t):
                    continue

                show_season.season = int(season_matches[0])

                if len(season_matches) > 1:
                    show_season.season_to = int(season_matches[1])

                if len(episodes) > 1:
                    show_season.episode = int(episodes[0])

                shows.append((t, show_season))

                if is_single_season(show_season.season, show_season.season_to):
                    all_seasons.add(show_season.season)
                elif show_season.season > 0 and show_season.season_to > 0:
                    # Include both endpoints for ranges like S01-S03.
                    all_seasons.update(range(show_season.season, show_season.season_to + 1))

            # For each season pick the best torrent
            for season in sorted(all_seasons):
                candidates = [s for s in shows if covers_season(s[1], season)]
                if not candidates:
                    continue

                best = [show for show in shows if show[1].torrent_id == candidates[0][1].torrent_id][0]
                for candidate in candidates[1:]:
                    candidate = [show for show in shows if show[1].torrent_id == candidate[1].torrent_id][0]
                    if better(candidate, best):
                        best = candidate

                # Persist one concrete row per selected season even when the
                # source torrent is a multi-season pack.
                selected = ShowSeason(
                    torrent_id=best[1].torrent_id,
                    season=season,
                    season_to=-1,
                    show_id=show_id,
                )
                self.config.show_season_repository.save(selected)
