    def _process_torrent_data(self, torrents: list[Torrent], is_serie = False) -> list[Torrent]:
        """
        Enrich each Torrent with its numeric ID, download key, quality tag,
        and fully formed download URL — all derived from page source and title text.
        """
        key = self._get_download_key()

        i = 0
        max = len(torrents)

        while i < max:
            torrent = torrents[i]
            match = self.ID_PATTERN.search(torrent.detail_link)
            if not match:
                raise ValueError(f"No valid 'id' parameter found in URL: {torrent.detail_link}")

            torrent.torrent_id = int(match.group(1))
            torrent.key = key
            torrent.quality = self._get_torrent_quality(torrent.title)
            torrent.download_link = self.config.get_torrent_download_url(torrent_id=torrent.torrent_id, key=key)

            if torrent.imdb_link == "":
                torrents.pop(i)
                i -= 1
                max -= 1
                continue

            if is_serie:
                seasons = re.findall(r"S(\d{1,2})", torrent.title)
                episodes = re.findall(r"E(\d{1,2})", torrent.title)

                if len(seasons) == 0:
                    torrents.pop(i)
                    i -= 1
                    max -= 1
                    continue

                torrent.season = int(seasons[0])

                if len(seasons) > 1:
                    torrent.season_to = int(seasons[1])

                if len(episodes) > 1:
                    torrent.episode = int(episodes[0])

            i += 1

        return torrents

    def _distillation_torrent_data(self, torrents: list[Torrent], is_serie = False) -> list[Torrent]:
        """
        Deduplicate torrents that share the same IMDB link, keeping only
        the highest-quality version. Entries with UNASSIGNED quality are
        always discarded when a better-quality duplicate exists.
        """
        # Build a dict keyed by IMDB link, keeping the best-quality Torrent
        best: dict[str, Torrent] = {}

        for torrent in torrents:
            key = torrent.imdb_link
            existing = best.get(key)

            if existing is None:
                best[key] = torrent
                continue

            # Prefer the torrent with the numerically higher quality value
            if torrent.quality == Quality.UNASSIGNED:
                continue  # Never replace a known-quality entry with an unassigned one
            if existing.quality == Quality.UNASSIGNED or int(torrent.quality.value) > int(existing.quality.value):
                best[key] = torrent

        return list(best.values())

    def _distillation_serie_torrent_data(self, torrents: list[Torrent]) -> list[Torrent]:
        """
        For each series (grouped by IMDB link), produce one Torrent per season.
        Preference order:
        1. Single-season torrents over multi-season packs
        2. Higher quality wins (SD=720 < HD=1080 < UHD=2160),
            but prefer lower quality over UNASSIGNED.
        """

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

        def is_single_season(t: Torrent) -> bool:
            return t.season_to == -1 and t.season > 0
        
        def is_an_episode(t: Torrent) -> bool:
            match = re.search(r'E(\d+)', t.title)
            return match is not None

        def covers_season(t: Torrent, season: int) -> bool:
            """True when this torrent contains the given season number."""
            if is_single_season(t):
                return t.season == season
            # multi-season pack: season_from..season_to
            if t.season > 0 and t.season_to > 0:
                return t.season <= season <= t.season_to
            return False

        def keep_most_common_prefix(items: list[Torrent]) -> list[Torrent]:
            # Extract first part of each title
            prefixes = [
                item.title.split('.')[0]
                for item in items
                if isinstance(item.title, str) and item.title
            ]

            if not prefixes:
                return items  # nothing to filter

            # Find most common prefix
            most_common_prefix, _ = Counter(prefixes).most_common(1)[0]

            # Keep only items that match it
            filtered = [
                item for item in items
                if item.title.split('.')[0] == most_common_prefix
            ]

            return filtered
            
        def better(challenger: Torrent, current: Torrent) -> bool:
            """
            Returns True if challenger should replace current.
            Single-season always beats multi-season pack.
            Within the same 'tier', lower quality_rank wins.
            """
            challenger_single = is_single_season(challenger)
            current_single    = is_single_season(current)

            if challenger_single and not current_single:
                return True   # single-season beats pack
            if not challenger_single and current_single:
                return False  # never replace single with pack

            # same tier → compare quality
            return quality_rank(challenger) < quality_rank(current)

        # --- group by series ---------------------------------------------------

        # imdb_link -> list of torrents for that series
        by_series: dict[str, list[Torrent]] = {}
        for torrent in torrents:
            if torrent.season <= 0:        # skip torrents with no season info
                continue
            by_series.setdefault(torrent.imdb_link, []).append(torrent)

        # --- pick one torrent per (series, season) -----------------------------

        result: list[Torrent] = []

        for imdb_link, series_torrents in by_series.items():
            # Find every season number that appears across all torrents
            all_seasons: set[int] = set()
            series_torrents = keep_most_common_prefix(series_torrents)

            for t in series_torrents:
                if t.imdb_link == "https://dereferer.link/?https://imdb.com/title/tt12637874/":
                    print('As')

                if is_an_episode(t):
                    continue

                if is_single_season(t):
                    all_seasons.add(t.season)
                elif t.season > 0 and t.season_to > 0:
                    all_seasons.update(range(t.season, t.season_to + 1)) # Todo: kell a +1?

            # For each season pick the best torrent
            for season in sorted(all_seasons):
                candidates = [t for t in series_torrents if covers_season(t, season)]
                if not candidates:
                    continue

                best = candidates[0]
                for candidate in candidates[1:]:
                    if better(candidate, best):
                        best = candidate

                result.append(best)

        return result
