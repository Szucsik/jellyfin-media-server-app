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
