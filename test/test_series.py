
"""
Tests for _distillation_serie_torrent_data logic.

We extract the pure distillation function here so the tests have zero
dependency on Selenium / SQLModel / ncore infrastructure.
All Torrent objects are plain dataclasses to keep things self-contained.
"""

import pytest
from dataclasses import dataclass
from enum import Enum


# ---------------------------------------------------------------------------
# Minimal model stubs (mirrors models.py, no SQLModel / DB required)
# ---------------------------------------------------------------------------

class Quality(Enum):
    UNASSIGNED = "UNASSIGNED"
    SD         = "720"
    HD         = "1080"
    UHD        = "2160"


@dataclass
class Torrent:
    title:                 str     = ""
    imdb_link:             str     = ""
    quality:               Quality = Quality.UNASSIGNED
    detail_link:           str     = ""
    download_link:         str     = ""
    torrent_id:            int     = -1
    key:                   str     = ""
    torrent_file_location: str     = ""
    downloaded:            bool    = False
    main_movie_file_path:  str     = ""
    season:    int = -1
    season_to: int = -1
    episode:   int = -1


# ---------------------------------------------------------------------------
# Pure distillation logic (standalone, no Selenium dependency)
# ---------------------------------------------------------------------------

def distillation_serie_torrent_data(torrents: list[Torrent]) -> list[Torrent]:
    """
    For each series (grouped by IMDB link), produce one Torrent per season.
    Preference order:
      1. Single-season torrents over multi-season packs.
      2. Lower resolution wins (SD=720 > HD=1080 > UHD=2160).
      3. Any assigned quality beats UNASSIGNED.
    """

    def quality_rank(t: Torrent) -> int:
        return {Quality.SD: 1, Quality.HD: 2, Quality.UHD: 3, Quality.UNASSIGNED: 99}.get(t.quality, 99)

    def is_single_season(t: Torrent) -> bool:
        return t.season_to == -1 and t.season > 0

    def covers_season(t: Torrent, season: int) -> bool:
        if is_single_season(t):
            return t.season == season
        if t.season > 0 and t.season_to > 0:
            return t.season <= season <= t.season_to
        return False

    def better(challenger: Torrent, current: Torrent) -> bool:
        ch_single  = is_single_season(challenger)
        cur_single = is_single_season(current)
        if ch_single and not cur_single:
            return True
        if not ch_single and cur_single:
            return False
        return quality_rank(challenger) < quality_rank(current)

    by_series: dict[str, list[Torrent]] = {}
    for torrent in torrents:
        if torrent.season <= 0:
            continue
        by_series.setdefault(torrent.imdb_link, []).append(torrent)

    result: list[Torrent] = []
    for imdb_link, series_torrents in by_series.items():
        all_seasons: set[int] = set()
        for t in series_torrents:
            if is_single_season(t):
                all_seasons.add(t.season)
            elif t.season > 0 and t.season_to > 0:
                all_seasons.update(range(t.season, t.season_to + 1))

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


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

_counter = 0

def make_torrent(
    title:     str,
    imdb:      str,
    quality:   Quality,
    season:    int,
    season_to: int = -1,
) -> Torrent:
    """Each call gets a unique torrent_id so identity (is) checks work reliably."""
    global _counter
    _counter += 1
    return Torrent(
        title=title, imdb_link=imdb, quality=quality,
        season=season, season_to=season_to, torrent_id=_counter,
    )


def entry_for_season(result: list[Torrent], season: int) -> Torrent:
    """
    Return the result entry that was chosen for the given season slot.

    Result entries are in ascending season order. Because pack torrents keep
    their original season/season_to fields (e.g. season=1, season_to=8), we
    cannot use a 'covers' predicate to find the S05 slot — the pack object
    would match *every* slot from 1 to 8.  We therefore index by position:
    collect every season number present across all torrents in the result,
    sort them, and return the element at the matching index.

    This mirrors exactly how distillation_serie_torrent_data builds its output.
    """
    # Gather all season numbers represented in this result list
    all_seasons: set[int] = set()
    for t in result:
        if t.season_to == -1 and t.season > 0:
            all_seasons.add(t.season)
        elif t.season > 0 and t.season_to > 0:
            all_seasons.update(range(t.season, t.season_to + 1))

    sorted_seasons = sorted(all_seasons)
    idx = sorted_seasons.index(season)   # raises ValueError if season not present
    return result[idx]


MODERN_FAMILY   = "https://www.imdb.com/title/tt1442437/"
GAME_OF_THRONES = "https://www.imdb.com/title/tt0944947/"
BREAKING_BAD    = "https://www.imdb.com/title/tt0903747/"


# ===========================================================================
# 1.  Basic – single series, single season
# ===========================================================================

class TestSingleSeriesSingleSeason:
    def test_one_torrent_in_one_torrent_out(self):
        torrents = [make_torrent("Show.S01.720p", MODERN_FAMILY, Quality.SD, season=1)]
        assert len(distillation_serie_torrent_data(torrents)) == 1

    def test_correct_object_identity_preserved(self):
        t = make_torrent("Show.S01.720p", MODERN_FAMILY, Quality.SD, season=1)
        assert distillation_serie_torrent_data([t])[0] is t

    def test_empty_input_returns_empty_list(self):
        assert distillation_serie_torrent_data([]) == []

    def test_torrent_with_no_season_is_ignored(self):
        t = make_torrent("Movie.2024.1080p", MODERN_FAMILY, Quality.HD, season=-1)
        assert distillation_serie_torrent_data([t]) == []

    def test_torrent_with_season_zero_is_ignored(self):
        t = make_torrent("Show.S00.720p", MODERN_FAMILY, Quality.SD, season=0)
        assert distillation_serie_torrent_data([t]) == []


# ===========================================================================
# 2.  Quality priority  SD (720) > HD (1080) > UHD (2160)
# ===========================================================================

class TestQualityPriority:

    def test_sd_beats_hd(self):
        sd = make_torrent("Show.S01.720p",  MODERN_FAMILY, Quality.SD, season=1)
        hd = make_torrent("Show.S01.1080p", MODERN_FAMILY, Quality.HD, season=1)
        assert distillation_serie_torrent_data([hd, sd])[0] is sd

    def test_sd_beats_uhd(self):
        sd  = make_torrent("Show.S01.720p",  MODERN_FAMILY, Quality.SD,  season=1)
        uhd = make_torrent("Show.S01.2160p", MODERN_FAMILY, Quality.UHD, season=1)
        assert distillation_serie_torrent_data([uhd, sd])[0] is sd

    def test_hd_beats_uhd(self):
        hd  = make_torrent("Show.S01.1080p", MODERN_FAMILY, Quality.HD,  season=1)
        uhd = make_torrent("Show.S01.2160p", MODERN_FAMILY, Quality.UHD, season=1)
        assert distillation_serie_torrent_data([uhd, hd])[0] is hd

    def test_known_quality_beats_unassigned(self):
        u  = make_torrent("Show.S01",       MODERN_FAMILY, Quality.UNASSIGNED, season=1)
        hd = make_torrent("Show.S01.1080p", MODERN_FAMILY, Quality.HD,         season=1)
        assert distillation_serie_torrent_data([u, hd])[0] is hd

    def test_sd_beats_unassigned(self):
        u  = make_torrent("Show.S01",      MODERN_FAMILY, Quality.UNASSIGNED, season=1)
        sd = make_torrent("Show.S01.720p", MODERN_FAMILY, Quality.SD,         season=1)
        assert distillation_serie_torrent_data([u, sd])[0] is sd

    def test_unassigned_kept_when_only_option(self):
        t = make_torrent("Show.S01", MODERN_FAMILY, Quality.UNASSIGNED, season=1)
        assert distillation_serie_torrent_data([t])[0] is t

    @pytest.mark.parametrize("order", [
        [0, 1, 2], [2, 1, 0], [1, 0, 2], [2, 0, 1],
    ])
    def test_sd_wins_regardless_of_input_order(self, order):
        sd  = make_torrent("Show.S01.720p",  MODERN_FAMILY, Quality.SD,  season=1)
        hd  = make_torrent("Show.S01.1080p", MODERN_FAMILY, Quality.HD,  season=1)
        uhd = make_torrent("Show.S01.2160p", MODERN_FAMILY, Quality.UHD, season=1)
        pool = [sd, hd, uhd]
        result = distillation_serie_torrent_data([pool[i] for i in order])
        assert result[0] is sd, f"SD should win for input order {order}"


# ===========================================================================
# 3.  Single-season preferred over multi-season pack
# ===========================================================================

class TestSingleSeasonVsPack:
    """
    Priority rule: a single-season torrent (e.g. Modern.Family.S07.720p) must
    always beat a multi-season pack (e.g. Game.of.Thrones.S01-S08.2160p)
    for the season it covers, even when the pack has higher quality.
    """

    def test_single_season_beats_pack_same_quality(self):
        """
        Input:  MF.S01-S11.720p (pack)  +  MF.S07.720p (single, same quality)
        S07 slot → single must win.
        """
        pack   = make_torrent("MF.S01-S11.720p", MODERN_FAMILY, Quality.SD, season=1, season_to=11)
        single = make_torrent("MF.S07.720p",     MODERN_FAMILY, Quality.SD, season=7)
        result = distillation_serie_torrent_data([pack, single])
        assert entry_for_season(result, 7) is single

    def test_single_sd_beats_pack_uhd(self):
        """
        Input:  GoT.S01-S08.2160p (pack, UHD)  +  GoT.S05.720p (single, SD)
        S05 slot → single SD wins over pack UHD.
        Single-season tier is checked before quality.
        """
        pack   = make_torrent("GoT.S01-S08.2160p", GAME_OF_THRONES, Quality.UHD, season=1, season_to=8)
        single = make_torrent("GoT.S05.720p",      GAME_OF_THRONES, Quality.SD,  season=5)
        result = distillation_serie_torrent_data([pack, single])
        assert entry_for_season(result, 5) is single

    def test_single_uhd_beats_pack_sd(self):
        """
        Even a UHD single beats a SD pack: single-season tier trumps quality.
        Input:  MF.S01-S11.720p (pack, SD)  +  MF.S03.2160p (single, UHD)
        S03 slot → single UHD wins.
        """
        pack   = make_torrent("MF.S01-S11.720p",  MODERN_FAMILY, Quality.SD,  season=1, season_to=11)
        single = make_torrent("MF.S03.2160p",     MODERN_FAMILY, Quality.UHD, season=3)
        result = distillation_serie_torrent_data([pack, single])
        assert entry_for_season(result, 3) is single

    def test_pack_fills_seasons_without_single(self):
        """
        Input:  GoT.S01-S08.720p (pack)  +  GoT.S03.720p (single)
        S03 → single; all other slots (1,2,4,5,6,7,8) → pack.
        """
        pack   = make_torrent("GoT.S01-S08.720p", GAME_OF_THRONES, Quality.SD, season=1, season_to=8)
        single = make_torrent("GoT.S03.720p",     GAME_OF_THRONES, Quality.SD, season=3)
        result = distillation_serie_torrent_data([pack, single])
        assert len(result) == 8
        assert entry_for_season(result, 3) is single
        for s in [1, 2, 4, 5, 6, 7, 8]:
            assert entry_for_season(result, s) is pack

    def test_pack_only_produces_one_entry_per_season(self):
        """A three-season pack with no singles → exactly three result entries, all the pack."""
        pack = make_torrent("Show.S01-S03.1080p", GAME_OF_THRONES, Quality.HD, season=1, season_to=3)
        result = distillation_serie_torrent_data([pack])
        assert len(result) == 3
        assert all(r is pack for r in result)

    def test_pack_never_replaces_single_regardless_of_quality_direction(self):
        """
        Input:  Show.S01-S05.720p (pack, SD)  +  Show.S02.2160p (single, UHD)
        S02 slot → single UHD wins even though its quality is 'worse' by the
        quality ranking; single-season tier has higher priority.
        """
        pack   = make_torrent("Show.S01-S05.720p",  MODERN_FAMILY, Quality.SD,  season=1, season_to=5)
        single = make_torrent("Show.S02.2160p",     MODERN_FAMILY, Quality.UHD, season=2)
        result = distillation_serie_torrent_data([pack, single])
        assert entry_for_season(result, 2) is single
        for s in [1, 3, 4, 5]:
            assert entry_for_season(result, s) is pack


# ===========================================================================
# 4.  Multiple independent series
# ===========================================================================

class TestMultipleSeries:

    def test_two_series_produce_two_results(self):
        a = make_torrent("MF.S01.720p",  MODERN_FAMILY,   Quality.SD, season=1)
        b = make_torrent("GoT.S01.720p", GAME_OF_THRONES, Quality.SD, season=1)
        assert len(distillation_serie_torrent_data([a, b])) == 2

    def test_each_series_picks_its_own_best_quality(self):
        mf_sd   = make_torrent("MF.S01.720p",   MODERN_FAMILY,   Quality.SD,  season=1)
        mf_uhd  = make_torrent("MF.S01.2160p",  MODERN_FAMILY,   Quality.UHD, season=1)
        got_hd  = make_torrent("GoT.S01.1080p", GAME_OF_THRONES, Quality.HD,  season=1)
        got_uhd = make_torrent("GoT.S01.2160p", GAME_OF_THRONES, Quality.UHD, season=1)
        result = distillation_serie_torrent_data([mf_uhd, mf_sd, got_uhd, got_hd])
        assert next(r for r in result if r.imdb_link == MODERN_FAMILY)   is mf_sd
        assert next(r for r in result if r.imdb_link == GAME_OF_THRONES) is got_hd

    def test_three_series_all_represented(self):
        torrents = [
            make_torrent("MF.S01.720p",  MODERN_FAMILY,   Quality.SD, season=1),
            make_torrent("GoT.S01.720p", GAME_OF_THRONES, Quality.SD, season=1),
            make_torrent("BB.S01.720p",  BREAKING_BAD,    Quality.SD, season=1),
        ]
        result = distillation_serie_torrent_data(torrents)
        assert len(result) == 3
        assert {r.imdb_link for r in result} == {MODERN_FAMILY, GAME_OF_THRONES, BREAKING_BAD}

    def test_series_do_not_cross_contaminate(self):
        """A UHD torrent in series A must not influence series B's selection."""
        a_sd  = make_torrent("MF.S01.720p",   MODERN_FAMILY,   Quality.SD,  season=1)
        a_uhd = make_torrent("MF.S01.2160p",  MODERN_FAMILY,   Quality.UHD, season=1)
        b_hd  = make_torrent("GoT.S01.1080p", GAME_OF_THRONES, Quality.HD,  season=1)
        result = distillation_serie_torrent_data([a_uhd, a_sd, b_hd])
        mf  = next(r for r in result if r.imdb_link == MODERN_FAMILY)
        got = next(r for r in result if r.imdb_link == GAME_OF_THRONES)
        assert mf  is a_sd   # MF picks SD
        assert got is b_hd   # GoT keeps its only torrent


# ===========================================================================
# 5.  Multi-season coverage
# ===========================================================================

class TestMultiSeasonCoverage:

    def test_five_single_season_torrents_all_returned(self):
        torrents = [
            make_torrent(f"BB.S0{s}.720p", BREAKING_BAD, Quality.SD, season=s)
            for s in range(1, 6)
        ]
        assert len(distillation_serie_torrent_data(torrents)) == 5

    def test_output_entries_are_in_ascending_season_order(self):
        """
        Input seasons deliberately shuffled; output must be 1, 2, 3, 4, 5.
        Each entry is a single-season torrent so r.season gives the correct
        season number directly.
        """
        torrents = [
            make_torrent(f"BB.S0{s}.720p", BREAKING_BAD, Quality.SD, season=s)
            for s in [3, 1, 5, 2, 4]
        ]
        result = distillation_serie_torrent_data(torrents)
        assert [r.season for r in result] == [1, 2, 3, 4, 5]

    def test_mixed_single_and_pack_correct_per_season_selection(self):
        """
        Modern Family S01-S11 pack (HD) + S07 single (SD).
        Expected: 11 entries; S07 slot → single; all other slots → pack.
        """
        pack   = make_torrent("MF.S01-S11.1080p", MODERN_FAMILY, Quality.HD, season=1, season_to=11)
        single = make_torrent("MF.S07.720p",      MODERN_FAMILY, Quality.SD, season=7)
        result = distillation_serie_torrent_data([pack, single])
        assert len(result) == 11
        assert entry_for_season(result, 7) is single
        for s in list(range(1, 7)) + list(range(8, 12)):
            assert entry_for_season(result, s) is pack

    def test_quality_chosen_independently_per_season(self):
        """
        BB S01: SD + HD candidates → SD wins.
        BB S02: UHD only → UHD is kept (only option).
        """
        s1_sd  = make_torrent("BB.S01.720p",  BREAKING_BAD, Quality.SD,  season=1)
        s1_hd  = make_torrent("BB.S01.1080p", BREAKING_BAD, Quality.HD,  season=1)
        s2_uhd = make_torrent("BB.S02.2160p", BREAKING_BAD, Quality.UHD, season=2)
        result = distillation_serie_torrent_data([s1_hd, s1_sd, s2_uhd])
        assert result[0] is s1_sd    # S01 → SD wins
        assert result[1] is s2_uhd   # S02 → only option kept

    def test_multiple_singles_and_pack_combined(self):
        """
        GoT S01-S08 pack (HD) + singles for S02 (SD) and S06 (UHD).
        S02 → single SD; S06 → single UHD; all others → pack.
        (Single always beats pack regardless of quality.)
        """
        pack   = make_torrent("GoT.S01-S08.1080p", GAME_OF_THRONES, Quality.HD,  season=1, season_to=8)
        s2     = make_torrent("GoT.S02.720p",       GAME_OF_THRONES, Quality.SD,  season=2)
        s6     = make_torrent("GoT.S06.2160p",      GAME_OF_THRONES, Quality.UHD, season=6)
        result = distillation_serie_torrent_data([pack, s2, s6])
        assert len(result) == 8
        assert entry_for_season(result, 2) is s2
        assert entry_for_season(result, 6) is s6
        for s in [1, 3, 4, 5, 7, 8]:
            assert entry_for_season(result, s) is pack


# ===========================================================================
# 6.  Edge cases
# ===========================================================================

class TestEdgeCases:

    def test_duplicate_identical_torrents_yields_one_entry(self):
        """Two identical single-season SD torrents → only one result entry."""
        t1 = make_torrent("Show.S01.720p", MODERN_FAMILY, Quality.SD, season=1)
        t2 = make_torrent("Show.S01.720p", MODERN_FAMILY, Quality.SD, season=1)
        assert len(distillation_serie_torrent_data([t1, t2])) == 1

    def test_pack_spanning_single_season_yields_one_result(self):
        """season=2, season_to=2 is a degenerate 'pack'; should produce one entry."""
        t = make_torrent("Show.S02-S02.720p", MODERN_FAMILY, Quality.SD, season=2, season_to=2)
        assert len(distillation_serie_torrent_data([t])) == 1

    def test_large_pack_s01_s08_produces_eight_entries(self):
        pack = make_torrent("GoT.S01-S08.1080p", GAME_OF_THRONES, Quality.HD, season=1, season_to=8)
        assert len(distillation_serie_torrent_data([pack])) == 8

    def test_single_for_one_season_does_not_affect_other_seasons_in_pack(self):
        """
        GoT S01-S08 pack (SD) + S05 single (SD).
        Only S05 slot changes; all other slots stay on the pack.
        """
        pack   = make_torrent("GoT.S01-S08.720p", GAME_OF_THRONES, Quality.SD, season=1, season_to=8)
        single = make_torrent("GoT.S05.720p",     GAME_OF_THRONES, Quality.SD, season=5)
        result = distillation_serie_torrent_data([pack, single])
        assert entry_for_season(result, 5) is single
        for s in [1, 2, 3, 4, 6, 7, 8]:
            assert entry_for_season(result, s) is pack

    def test_two_overlapping_packs_sd_wins_every_slot(self):
        """
        SD pack S01-S04 vs HD pack S01-S04 → SD must win for every season.
        """
        sd_pack = make_torrent("Show.S01-S04.720p",  MODERN_FAMILY, Quality.SD, season=1, season_to=4)
        hd_pack = make_torrent("Show.S01-S04.1080p", MODERN_FAMILY, Quality.HD, season=1, season_to=4)
        result = distillation_serie_torrent_data([hd_pack, sd_pack])
        assert len(result) == 4
        assert all(r is sd_pack for r in result)

    def test_only_movie_torrents_returns_empty(self):
        movies = [
            make_torrent("Movie.2022.1080p", MODERN_FAMILY,   Quality.HD, season=-1),
            make_torrent("Movie.2023.720p",  GAME_OF_THRONES, Quality.SD, season=-1),
        ]
        assert distillation_serie_torrent_data(movies) == []

    def test_mixed_movie_and_series_only_series_returned(self):
        movie  = make_torrent("Movie.2022.1080p", MODERN_FAMILY, Quality.HD, season=-1)
        series = make_torrent("Show.S01.720p",    MODERN_FAMILY, Quality.SD, season=1)
        result = distillation_serie_torrent_data([movie, series])
        assert len(result) == 1
        assert result[0] is series

    def test_three_packs_with_ascending_quality_sd_wins(self):
        """Ensure quality_rank comparison works across all three Quality levels."""
        sd_pack  = make_torrent("BB.S01-S05.720p",  BREAKING_BAD, Quality.SD,  season=1, season_to=5)
        hd_pack  = make_torrent("BB.S01-S05.1080p", BREAKING_BAD, Quality.HD,  season=1, season_to=5)
        uhd_pack = make_torrent("BB.S01-S05.2160p", BREAKING_BAD, Quality.UHD, season=1, season_to=5)
        result = distillation_serie_torrent_data([uhd_pack, hd_pack, sd_pack])
        assert len(result) == 5
        assert all(r is sd_pack for r in result)
