"""Tests for the pure parsing helpers in data_processing/utils/file_processing_utils.py."""
from __future__ import annotations

from unittest.mock import patch, Mock

import pytest

from data_processing.utils.file_processing_utils import (
    Episode,
    FileProcessingUtils,
    Season,
    Show,
    VIDEO_EXTS,
)


@pytest.fixture
def utils():
    return FileProcessingUtils()


# ── small unit helpers ───────────────────────────────────────────────────────

class TestIsSample:
    def test_detects_sample_folder(self, utils):
        assert utils.is_sample(["Show.S01", "Sample", "x.mkv"]) is True

    def test_detects_sample_in_lowercase(self, utils):
        assert utils.is_sample(["show", "sample.dir", "x.mkv"]) is True

    def test_no_sample(self, utils):
        assert utils.is_sample(["Show.S01", "S01E01.mkv"]) is False


class TestParseShowInfo:
    def test_show_with_year(self, utils):
        name, year = utils.parse_show_info("Breaking.Bad.2008.S01.1080p")
        assert name == "Breaking Bad"
        assert year == "2008"

    def test_show_without_year(self, utils):
        name, year = utils.parse_show_info("Yellowstone.S04.1080p")
        assert name == "Yellowstone"
        assert year is None

    def test_underscores_become_spaces(self, utils):
        name, year = utils.parse_show_info("Game_Of_Thrones_S01")
        assert "Game" in name and "Thrones" in name


class TestParseEpisode:
    def test_standard_sxxexx(self, utils):
        s, e1, e2 = utils.parse_episode("Show.S01E05.mkv")
        assert (s, e1, e2) == (1, 5, None)

    def test_dot_separator(self, utils):
        s, e1, e2 = utils.parse_episode("Show.S01.E05.mkv")
        assert (s, e1, e2) == (1, 5, None)

    def test_double_episode(self, utils):
        s, e1, e2 = utils.parse_episode("Show.S02E03-E04.mkv")
        assert (s, e1, e2) == (2, 3, 4)

    def test_nxnn_format(self, utils):
        s, e1, e2 = utils.parse_episode("Show.1x02.mkv")
        assert (s, e1, e2) == (1, 2, None)

    def test_no_match(self, utils):
        s, e1, e2 = utils.parse_episode("randomfile.mkv")
        assert (s, e1, e2) == (None, None, None)


class TestFormatEpFilename:
    def test_single_episode(self, utils):
        assert utils.format_ep_filename("Show", 1, 5, None, ".mkv") == "Show S01E05.mkv"

    def test_double_episode(self, utils):
        assert utils.format_ep_filename("Show", 2, 3, 4, ".mkv") == "Show S02E03-E04.mkv"


class TestParseShowInfoFromFilename:
    def test_yellowstone(self, utils):
        name, year = utils.parse_show_info_from_filename("sln-720p.yellowstone.401.mkv")
        assert name == "Yellowstone"
        assert year is None

    def test_breaking_bad_no_year_token_eats_year_as_episode(self, utils):
        # NOTE: bare 4-digit year tokens collide with the episode-token
        # regex (\d{3,4}) and stop the show-name scan early. Documented
        # behaviour, not what we'd ideally want.
        name, _ = utils.parse_show_info_from_filename("grp.1080p.breaking.bad.512.mkv")
        assert name == "Breaking Bad"

    def test_unknown_when_empty(self, utils):
        name, _ = utils.parse_show_info_from_filename("720p.401.mkv")
        assert name == "Unknown"

    def test_with_sxxexx_token(self, utils):
        name, _ = utils.parse_show_info_from_filename("rip.1080p.dexter.S04E01.mkv")
        assert name == "Dexter"


class TestParseEpisodeSequence:
    def test_seep_token_decoding(self, utils):
        results = utils.parse_episode_sequence(
            ["x.401.mkv", "x.402.mkv", "x.403.mkv"]
        )
        assert results == [(4, 1, None), (4, 2, None), (4, 3, None)]

    def test_seep_with_zero_episode_is_none(self, utils):
        # Token "400" → episode==0 is ambiguous; library returns (None, None, None)
        results = utils.parse_episode_sequence(["x.400.mkv", "x.401.mkv"])
        assert results[0] == (None, None, None)
        assert results[1] == (4, 1, None)

    def test_single_low_token_is_episode_only(self, utils):
        results = utils.parse_episode_sequence(["x.5.mkv", "x.6.mkv"])
        assert results == [(None, 5, None), (None, 6, None)]

    def test_no_tokens_returns_none_tuples(self, utils):
        results = utils.parse_episode_sequence(["foo.mkv", "bar.mkv"])
        assert results == [(None, None, None), (None, None, None)]

    def test_empty_input(self, utils):
        assert utils.parse_episode_sequence([]) == []

    def test_unrealistic_season_token_is_rejected(self, utils):
        results = utils.parse_episode_sequence(["x.202301.mkv", "x.202302.mkv"])
        assert results == [(None, None, None), (None, None, None)]


class TestParse:
    def test_parses_folder_based_show(self, utils):
        lines = [
            "Breaking.Bad.S01/Breaking.Bad.S01E01.mkv",
            "Breaking.Bad.S01/Breaking.Bad.S01E02.mkv",
        ]
        shows = utils.parse(lines)
        assert len(shows) == 1
        s = shows[0]
        assert s.name == "Breaking Bad"
        assert len(s.seasons) == 1
        assert len(s.seasons[0].episodes) == 2

    def test_parses_double_episode(self, utils):
        lines = ["Show.S01/Show.S01E03-E04.mkv"]
        shows = utils.parse(lines)
        ep = shows[0].seasons[0].episodes[0]
        assert ep.episode == 3
        assert ep.episode_end == 4

    def test_skips_sample(self, utils):
        lines = [
            "Show.S01/Sample/sample.mkv",
            "Show.S01/Show.S01E01.mkv",
        ]
        shows = utils.parse(lines)
        eps = shows[0].seasons[0].episodes
        assert len(eps) == 1

    @pytest.mark.parametrize(
        "folder_name",
        ["extras", "EXTRAS", "Extras", "sample", "Samples"],
    )
    def test_skips_excluded_show_directories(self, utils, folder_name):
        lines = [
            f"Show.S01/{folder_name}/Show.S01E99.mkv",
            "Show.S01/Show.S01E01.mkv",
        ]
        shows = utils.parse(lines)
        eps = shows[0].seasons[0].episodes
        assert len(eps) == 1
        assert eps[0].episode == 1

    def test_skips_non_video(self, utils):
        lines = ["Show.S01/notes.txt"]
        assert utils.parse(lines) == []

    def test_blank_lines_ignored(self, utils):
        lines = ["", "   ", "Show.S01/Show.S01E01.mkv"]
        shows = utils.parse(lines)
        assert len(shows[0].seasons[0].episodes) == 1

    def test_flat_filenames_with_sequence_fallback(self, utils):
        lines = ["sln-720p.yellowstone.401.mkv", "sln-720p.yellowstone.402.mkv"]
        shows = utils.parse(lines)
        assert shows[0].name == "Yellowstone"
        eps = shows[0].seasons[0].episodes
        assert [(e.season, e.episode) for e in eps] == [(4, 1), (4, 2)]

    def test_sorts_episodes(self, utils):
        lines = [
            "Show.S01/Show.S01E03.mkv",
            "Show.S01/Show.S01E01.mkv",
            "Show.S01/Show.S01E02.mkv",
        ]
        shows = utils.parse(lines)
        eps = shows[0].seasons[0].episodes
        assert [e.episode for e in eps] == [1, 2, 3]

    def test_messy_flat_seep_files_grouped_as_one_show(self, utils):
        """Flat files whose names start with the episode code must all end up
        in a single Show rather than one Show per file."""
        lines = [
            "101_episode.mkv",
            "102_asdasd.mkv",
            "111.sode.mkv",
        ]
        shows = utils.parse(lines)
        assert len(shows) == 1, "All files must belong to one Show"
        eps = shows[0].seasons[0].episodes
        assert [(e.season, e.episode) for e in eps] == [(1, 1), (1, 2), (1, 11)]

    def test_messy_flat_seep_bare_numbers(self, utils):
        """Bare 3-digit SEEP filenames with no descriptive tokens."""
        lines = ["101.mkv", "102.mkv", "111.mkv"]
        shows = utils.parse(lines)
        assert len(shows) == 1
        eps = shows[0].seasons[0].episodes
        assert [(e.season, e.episode) for e in eps] == [(1, 1), (1, 2), (1, 11)]

    def test_messy_flat_seep_with_folder_context(self, utils):
        """When files ARE inside a folder the show name comes from the folder
        and sequence detection still works for the same messy patterns."""
        lines = [
            "MyShow/101_episode.mkv",
            "MyShow/102_asdasd.mkv",
            "MyShow/111.sode.mkv",
        ]
        shows = utils.parse(lines)
        assert len(shows) == 1
        eps = shows[0].seasons[0].episodes
        assert [(e.season, e.episode) for e in eps] == [(1, 1), (1, 2), (1, 11)]


class TestDirectoryStructureDetection:
    """Season numbers are taken from consecutive season directories and episodes
    from the numeric token that increases sequentially within each directory."""

    def test_consecutive_season_dirs(self, utils):
        lines = [
            "Sherlock.S01-S04.COMPLETE.720p.BluRay-pcroland/"
            "Sherlock.S01.720p.BluRay.DD5.1.x264.HUN.ENG-pcroland/"
            "Sherlock.S01E01.720p.BluRay.DD5.1.x264.HUN.ENG-pcroland.mkv",
            "Sherlock.S01-S04.COMPLETE.720p.BluRay-pcroland/"
            "Sherlock.S01.720p.BluRay.DD5.1.x264.HUN.ENG-pcroland/"
            "Sherlock.S01E02.720p.BluRay.DD5.1.x264.HUN.ENG-pcroland.mkv",
            "Sherlock.S01-S04.COMPLETE.720p.BluRay-pcroland/"
            "Sherlock.S01.720p.BluRay.DD5.1.x264.HUN.ENG-pcroland/"
            "Sherlock.S01E03.720p.BluRay.DD5.1.x264.HUN.ENG-pcroland.mkv",
            "Sherlock.S01-S04.COMPLETE.720p.BluRay-pcroland/"
            "Sherlock.S02.720p.BluRay.DD5.1.x264.HUN.ENG-pcroland/"
            "Sherlock.S02E01.720p.BluRay.DD5.1.x264.HUN.ENG-pcroland.mkv",
        ]
        shows = utils.parse(lines)
        assert len(shows) == 1
        show = shows[0]
        assert show.name == "Sherlock"
        assert [s.number for s in show.seasons] == [1, 2]
        assert [(e.season, e.episode) for e in show.seasons[0].episodes] == [(1, 1), (1, 2), (1, 3)]
        assert [(e.season, e.episode) for e in show.seasons[1].episodes] == [(2, 1)]

    def test_season_from_directory_overrides_misleading_filename_numbers(self, utils):
        """Filenames carry unrelated release IDs; season comes from the directory
        and the episode from the sequentially-increasing token."""
        lines = [
            "Show.S03.1080p.WEB-grp/Show.WEB.554213.1080p-grp.1.mkv",
            "Show.S03.1080p.WEB-grp/Show.WEB.554213.1080p-grp.2.mkv",
            "Show.S04.1080p.WEB-grp/Show.WEB.554213.1080p-grp.1.mkv",
            "Show.S04.1080p.WEB-grp/Show.WEB.554213.1080p-grp.2.mkv",
        ]
        shows = utils.parse(lines)
        assert len(shows) == 1
        show = shows[0]
        assert [s.number for s in show.seasons] == [3, 4]
        assert [(e.season, e.episode) for e in show.seasons[0].episodes] == [(3, 1), (3, 2)]
        assert [(e.season, e.episode) for e in show.seasons[1].episodes] == [(4, 1), (4, 2)]

    def test_non_consecutive_seasons_fall_back(self, utils):
        """Gap in the season sequence (1, 3) → directory detection is skipped and
        the standard SxxExx filename parsing takes over."""
        lines = [
            "Show.S01/Show.S01E01.mkv",
            "Show.S03/Show.S03E01.mkv",
        ]
        shows = utils.parse(lines)
        assert len(shows) == 1
        numbers = sorted(s.number for s in shows[0].seasons)
        assert numbers == [1, 3]

    def test_unrealistic_season_numbers_fall_back(self, utils):
        """Directory 'season' numbers above the cap (e.g. 323, 1545) are not real
        seasons; directory detection is skipped so no bogus high season survives."""
        lines = [
            "Show.S323.720p/Show.S01E01.720p.mkv",
            "Show.S324.720p/Show.S01E02.720p.mkv",
        ]
        shows = utils.parse(lines)
        # Season must come from the filenames (S01), never the 323/324 directories.
        all_seasons = [s.number for show in shows for s in show.seasons]
        assert all(n <= 40 for n in all_seasons)
        assert 323 not in all_seasons and 324 not in all_seasons

    def test_season_number_at_cap_is_allowed(self, utils):
        """Seasons up to the cap (40) are accepted."""
        lines = [
            "Show.S39.720p/Show.S39E01.720p.mkv",
            "Show.S40.720p/Show.S40E01.720p.mkv",
        ]
        shows = utils.parse(lines)
        assert [s.number for s in shows[0].seasons] == [39, 40]

    def test_single_season_directory_with_multiple_files(self, utils):
        """Multiple media files in one season directory → that directory is a
        season; the season number comes from the directory name."""
        lines = [
            "Vikings.S03.1080p-grp/Vikings.S03.1080p.x265-grp.1.mkv",
            "Vikings.S03.1080p-grp/Vikings.S03.1080p.x265-grp.2.mkv",
            "Vikings.S03.1080p-grp/Vikings.S03.1080p.x265-grp.3.mkv",
        ]
        shows = utils.parse(lines)
        assert len(shows) == 1
        show = shows[0]
        assert [s.number for s in show.seasons] == [3]
        assert [(e.season, e.episode) for e in show.seasons[0].episodes] == [(3, 1), (3, 2), (3, 3)]

    def test_episode_ignores_release_id_picks_sequential_value(self, utils):
        """Every numeric value is examined; the constant release ID is ignored and
        the value that increases one-by-one becomes the episode number."""
        lines = [
            "Show.S02.1080p/Show.998877.1080p.x265.1.mkv",
            "Show.S02.1080p/Show.998877.1080p.x265.2.mkv",
            "Show.S02.1080p/Show.998877.1080p.x265.3.mkv",
        ]
        shows = utils.parse(lines)
        eps = shows[0].seasons[0].episodes
        assert [(e.season, e.episode) for e in eps] == [(2, 1), (2, 2), (2, 3)]

    def test_episode_token_found_via_right_alignment(self, utils):
        """The episode number sits at the end while a leading number varies; the
        right-aligned scan still locates the one-by-one sequence."""
        lines = [
            "Show.S05.720p/2021.Show.x264.1.mkv",
            "Show.S05.720p/2022.Show.x264.2.mkv",
            "Show.S05.720p/2023.Show.x264.3.mkv",
        ]
        shows = utils.parse(lines)
        eps = shows[0].seasons[0].episodes
        assert [(e.season, e.episode) for e in eps] == [(5, 1), (5, 2), (5, 3)]

    def test_double_episode_preserved_via_fallback(self, utils):
        """When the sequential token is ambiguous (double episodes), the per-file
        standard parser still resolves SxxExx-Exx including the episode end."""
        lines = [
            "Show.S01.720p/Show.S01E01-E02.720p.mkv",
            "Show.S02.720p/Show.S02E01-E02.720p.mkv",
        ]
        shows = utils.parse(lines)
        assert [s.number for s in shows[0].seasons] == [1, 2]
        first = shows[0].seasons[0].episodes[0]
        assert (first.season, first.episode, first.episode_end) == (1, 1, 2)


class TestExtractSeasonFromDir:
    @pytest.mark.parametrize(
        "directory,expected",
        [
            ("Show.S01.720p.BluRay", 1),
            ("Show.S12.1080p", 12),
            ("Season 3", 3),
            ("Season_04", 4),
            ("Show.1080p.WEB", None),
            ("Show.S40.720p", 40),
            ("Show.S41.720p", None),
            ("Show.S323.720p", None),
            ("Show.S1545.720p", None),
        ],
    )
    def test_extraction(self, utils, directory, expected):
        assert utils._extract_season_from_dir(directory) == expected


class TestTmdbLookup:
    def test_movie_result(self, utils):
        with patch("data_processing.utils.file_processing_utils.requests.get") as mocked:
            mocked.return_value.json.return_value = {
                "movie_results": [{"title": "Inception"}],
                "tv_results": [],
            }
            name = utils.get_name_by_id_from_tmdb("tt1375666", "key")
            assert name == "Inception [imdbid-tt1375666]"

    def test_tv_result(self, utils):
        with patch("data_processing.utils.file_processing_utils.requests.get") as mocked:
            mocked.return_value.json.return_value = {
                "movie_results": [],
                "tv_results": [{"name": "Breaking Bad"}],
            }
            assert utils.get_name_by_id_from_tmdb("ttX", "key") == "Breaking Bad [imdbid-ttX]"

    def test_no_result(self, utils):
        with patch("data_processing.utils.file_processing_utils.requests.get") as mocked:
            mocked.return_value.json.return_value = {"movie_results": [], "tv_results": []}
            assert utils.get_name_by_id_from_tmdb("ttX", "key") == ""


class TestGetShow:
    def test_delegates_to_parse(self, utils):
        result = utils.get_show(["Show.S01/Show.S01E01.mkv"])
        assert isinstance(result[0], Show)


def test_video_exts_constant():
    assert ".mkv" in VIDEO_EXTS
    assert ".mp4" in VIDEO_EXTS


def test_dataclasses_default_factories():
    s = Season(number=1)
    assert s.episodes == []
    sh = Show(name="x", year=None)
    assert sh.seasons == []
    e = Episode(season=1, episode=1, episode_end=None, filename="a.mkv", original_path="x/a.mkv")
    assert e.season == 1
