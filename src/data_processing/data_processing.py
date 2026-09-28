from config import Configuration
from models.show import Show
from models.torrent import Quality, Torrent
from models.show_season import ShowSeason
from models.movie import Movie

from collections import deque

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
            Quality.HD:         1,   # 1080p  – most preferred
            Quality.UHD:        2,   # 2160p
            Quality.SD:         3,   # 720p
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

        def get_quality_torrents(t: list[tuple[Torrent, ShowSeason]], q: Quality) -> list[tuple[Torrent, ShowSeason]]:
            """Lower rank = more preferred (we use min-selection)."""
            preferred: list[tuple[Torrent, ShowSeason]] = []

            for torrent in t:
                if torrent[0].quality == q:
                    preferred.append(torrent)

            return preferred

        def is_single_season(season: int, season_to: int) -> bool:
            return season_to == -1 and season > 0
        
        def is_an_episode(t: Torrent) -> bool:
            match = re.search(r'E(\d+)', t.title)
            return match is not None

        def find_best_matching_seasons(numbers: list[int], elements: list[tuple[Torrent, ShowSeason]]):
            # Exact-cover of the required seasons by non-overlapping torrent
            # intervals. Each element covers [season, season_to] (or a single
            # season); ranges never cross a gap, so every integer they span is
            # a required season. In any exact cover the interval containing the
            # smallest uncovered season must start at that season, which lets us
            # solve it with a BFS over the sorted seasons instead of trying all
            # 2^n subsets. BFS also yields the cover using the fewest torrents.
            targets = sorted(set(numbers))
            if not targets:
                return None

            target_set = set(targets)
            index_of = {season: i for i, season in enumerate(targets)}

            # season_start -> list of (season_end, element), input order preserved
            starts: dict[int, list[tuple[int, tuple[Torrent, ShowSeason]]]] = {}
            for element in elements:
                show_season = element[1]
                start = show_season.season
                end = show_season.season_to if show_season.season_to > start else start
                if start not in target_set:
                    continue
                if any(season not in target_set for season in range(start, end + 1)):
                    continue
                starts.setdefault(start, []).append((end, element))

            n = len(targets)
            visited = [False] * (n + 1)
            visited[0] = True
            parent: dict[int, tuple[int, tuple[Torrent, ShowSeason]]] = {}
            queue = deque([0])

            while queue:
                i = queue.popleft()
                if i == n:
                    break
                for end, element in starts.get(targets[i], ()):
                    nxt = index_of[end] + 1
                    if not visited[nxt]:
                        visited[nxt] = True
                        parent[nxt] = (i, element)
                        queue.append(nxt)

            if not visited[n]:
                return None

            chosen: list[tuple[Torrent, ShowSeason]] = []
            node = n
            while node in parent:
                prev_i, element = parent[node]
                chosen.append(element)
                node = prev_i
            chosen.reverse()
            return chosen

        # --- group by series ---------------------------------------------------

        # imdb_link -> list of torrents for that series
        by_series: dict[str, list[Torrent]] = {}
        for torrent in torrents:
            if torrent.imdb_link != "":
                by_series.setdefault(torrent.imdb_link, []).append(torrent)

        # --- pick one torrent per (series, season) -----------------------------

        result: list[Torrent] = []

        # Iterate over each show seasons grouped by IMDB link
        total_series = len(by_series)
        for series_index, (imdb_link, series_torrents) in enumerate(by_series.items(), start=1):
            self.logger.info(
                "Starting to process tv show %s (%s/%s)",
                series_torrents[0].title,
                series_index,
                total_series,
            )
            self.logger.info(f"Number of torrent records: {len(series_torrents)}")
            # Find every season number that appears across all torrents
            all_seasons: set[int] = set()

            # We need the Torrent and the Showseason together
            # We use the Torrent for getting the correct quality seasons...
            torrent_and_showseason: list[tuple[Torrent, ShowSeason]] = []

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

                torrent_and_showseason.append((t, show_season))

                if is_single_season(show_season.season, show_season.season_to):
                    all_seasons.add(show_season.season)
                elif show_season.season > 0 and show_season.season_to > 0:
                    # Include both endpoints for ranges like S01-S03.
                    all_seasons.update(range(show_season.season, show_season.season_to + 1))


            # New implementation
            if len(all_seasons) > 0:
                hd_shows: list[Torrent] = get_quality_torrents(t=torrent_and_showseason, q=Quality.HD)
                sd_shows: list[Torrent] = get_quality_torrents(t=torrent_and_showseason, q=Quality.SD)
                uhd_shows: list[Torrent] = get_quality_torrents(t=torrent_and_showseason, q=Quality.UHD)

                optimal_seasons = find_best_matching_seasons(numbers=all_seasons, elements=hd_shows)
                
                if optimal_seasons == None:
                    optimal_seasons = find_best_matching_seasons(numbers=all_seasons, elements=sd_shows)

                if optimal_seasons == None:
                    optimal_seasons = find_best_matching_seasons(numbers=all_seasons, elements=uhd_shows)

                if optimal_seasons == None:
                    optimal_seasons = find_best_matching_seasons(numbers=all_seasons, elements=torrent_and_showseason)

                for optimal_season in optimal_seasons:
                    # Show season 
                    show = self.config.show_repository.find_first_by(imdb_link=imdb_link)
                    if show is None:
                        show = self.config.show_repository.save(Show(imdb_link=imdb_link))
                    show_id = show.id

                    selected = ShowSeason(
                        torrent_id=optimal_season[1].torrent_id,
                        season=optimal_season[1].season,
                        season_to=optimal_season[1].season_to,
                        show_id=show_id,
                    )

                    self.config.show_season_repository.save_if_new(selected)