"""Comprehensive tests for src/data_processing/data_processing.py.

The class under test mutates the database via repositories that we replace
with in-memory equivalents in the ``fake_config`` fixture (see conftest).
"""
from __future__ import annotations

import pytest

from data_processing.data_processing import DataProcessing
from models.show_season import ShowSeason
from models.torrent import Quality, Torrent


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _save(repos, torrent: Torrent) -> Torrent:
    """Persist a torrent through the repository so we get a real id back."""
    return repos.torrent.save(torrent)


def _process(fake_config) -> DataProcessing:
    return DataProcessing(config=fake_config)


# ─────────────────────────────────────────────────────────────────────────────
#  Movie deduplication
# ─────────────────────────────────────────────────────────────────────────────

class TestMovieDeduplication:
    def test_single_movie_creates_single_movie_row(self, fake_config, repos):
        _save(repos, Torrent(torrent_id=1, title="Foo.2020.1080p", imdb_link="tt1", quality=Quality.HD, is_show=False))
        _process(fake_config).process()
        movies = repos.movie.get_all()
        assert len(movies) == 1

    def test_duplicate_imdb_keeps_best_quality(self, fake_config, repos):
        # Order: HD=1 (most preferred), UHD=2, SD=3
        sd = _save(repos, Torrent(torrent_id=1, title="x.SD", imdb_link="ttX", quality=Quality.SD, is_show=False))
        hd = _save(repos, Torrent(torrent_id=2, title="x.HD", imdb_link="ttX", quality=Quality.HD, is_show=False))
        uhd = _save(repos, Torrent(torrent_id=3, title="x.UHD", imdb_link="ttX", quality=Quality.UHD, is_show=False))

        _process(fake_config).process()
        movies = repos.movie.get_all()
        assert len(movies) == 1
        assert movies[0].torrent_id == hd.id

    def test_unassigned_never_replaces_known_quality(self, fake_config, repos):
        unk = _save(repos, Torrent(torrent_id=1, title="x.UNK", imdb_link="ttX", quality=Quality.UNASSIGNED, is_show=False))
        sd = _save(repos, Torrent(torrent_id=2, title="x.SD", imdb_link="ttX", quality=Quality.SD, is_show=False))
        _process(fake_config).process()
        movies = repos.movie.get_all()
        assert len(movies) == 1
        assert movies[0].torrent_id == sd.id

    def test_known_quality_replaces_unassigned(self, fake_config, repos):
        unk = _save(repos, Torrent(torrent_id=1, title="x.UNK", imdb_link="ttX", quality=Quality.UNASSIGNED, is_show=False))
        hd = _save(repos, Torrent(torrent_id=2, title="x.HD", imdb_link="ttX", quality=Quality.HD, is_show=False))
        _process(fake_config).process()
        movies = repos.movie.get_all()
        assert movies[0].torrent_id == hd.id

    def test_only_unassigned_still_kept(self, fake_config, repos):
        u1 = _save(repos, Torrent(torrent_id=1, title="x", imdb_link="ttX", quality=Quality.UNASSIGNED, is_show=False))
        _process(fake_config).process()
        assert len(repos.movie.get_all()) == 1

    def test_distinct_imdb_links_are_kept_separately(self, fake_config, repos):
        _save(repos, Torrent(torrent_id=1, title="a", imdb_link="tt1", quality=Quality.HD, is_show=False))
        _save(repos, Torrent(torrent_id=2, title="b", imdb_link="tt2", quality=Quality.HD, is_show=False))
        _save(repos, Torrent(torrent_id=3, title="c", imdb_link="tt3", quality=Quality.SD, is_show=False))
        _process(fake_config).process()
        assert len(repos.movie.get_all()) == 3

    def test_empty_input_does_nothing(self, fake_config, repos):
        _process(fake_config).process()
        assert repos.movie.get_all() == []
        assert repos.show.get_all() == []

    def test_movie_with_uhd_only_is_picked(self, fake_config, repos):
        u = _save(repos, Torrent(torrent_id=1, title="Foo", imdb_link="ttU", quality=Quality.UHD, is_show=False))
        _process(fake_config).process()
        movies = repos.movie.get_all()
        assert movies[0].torrent_id == u.id


# ─────────────────────────────────────────────────────────────────────────────
#  Show + season selection
# ─────────────────────────────────────────────────────────────────────────────

class TestShowSeasonSelection:
    def test_single_show_single_season(self, fake_config, repos):
        _save(repos, Torrent(torrent_id=1, title="Show.S01.1080p", imdb_link="ttA", quality=Quality.HD, is_show=True))
        _process(fake_config).process()

        shows = repos.show.get_all()
        seasons = repos.show_season.get_all()
        assert len(shows) == 1
        assert shows[0].imdb_link == "ttA"
        assert len(seasons) == 1
        assert seasons[0].season == 1
        assert seasons[0].season_to == -1
        assert seasons[0].show_id == shows[0].id

    def test_multi_season_beats_single_season_pack(self, fake_config, repos):
        single = _save(repos, Torrent(torrent_id=1, title="Show.S02.1080p", imdb_link="ttB", quality=Quality.HD, is_show=True))
        pack = _save(repos, Torrent(torrent_id=2, title="Show.S01.S04.1080p", imdb_link="ttB", quality=Quality.SD, is_show=True))

        _process(fake_config).process()

        seasons = repos.show_season.get_all()
        # Season 2 should be the single, seasons 1/3/4 from pack
        s2 = next(s for s in seasons if s.season == 1 and s.season_to == 4)
        assert s2.torrent_id == pack.id

    def test_quality_priority_within_single_season(self, fake_config, repos):
        # SD=1 most preferred → SD wins over HD/UHD when both are single-season
        sd = _save(repos, Torrent(torrent_id=1, title="Show.S01.720p", imdb_link="ttC", quality=Quality.SD, is_show=True))
        hd = _save(repos, Torrent(torrent_id=2, title="Show.S01.1080p", imdb_link="ttC", quality=Quality.HD, is_show=True))
        uhd = _save(repos, Torrent(torrent_id=3, title="Show.S01.2160p", imdb_link="ttC", quality=Quality.UHD, is_show=True))

        _process(fake_config).process()
        seasons = repos.show_season.get_all()
        assert len(seasons) == 1
        assert seasons[0].torrent_id == hd.id

    def test_unassigned_quality_loses(self, fake_config, repos):
        unk = _save(repos, Torrent(torrent_id=1, title="Show.S01.WEB", imdb_link="ttD", quality=Quality.UNASSIGNED, is_show=True))
        hd = _save(repos, Torrent(torrent_id=2, title="Show.S01.1080p", imdb_link="ttD", quality=Quality.HD, is_show=True))

        _process(fake_config).process()
        seasons = repos.show_season.get_all()
        assert seasons[0].torrent_id == hd.id

    def test_episode_torrent_is_skipped(self, fake_config, repos):
        # E\d+ in title → treated as a single-episode torrent and dropped
        ep = _save(repos, Torrent(torrent_id=1, title="Show.S01E01.1080p", imdb_link="ttE", quality=Quality.HD, is_show=True))
        season = _save(repos, Torrent(torrent_id=2, title="Show.S01.1080p", imdb_link="ttE", quality=Quality.HD, is_show=True))

        _process(fake_config).process()
        seasons = repos.show_season.get_all()
        assert len(seasons) == 1
        assert seasons[0].torrent_id == season.id

    def test_torrent_without_season_pattern_is_skipped(self, fake_config, repos):
        # No SXX → dropped during show processing
        _save(repos, Torrent(torrent_id=1, title="Random.Title.1080p", imdb_link="ttF", quality=Quality.HD, is_show=True))
        _process(fake_config).process()
        assert repos.show_season.get_all() == []

    def test_multiple_distinct_shows(self, fake_config, repos):
        _save(repos, Torrent(torrent_id=1, title="A.S01.1080p", imdb_link="ttA", quality=Quality.HD, is_show=True))
        _save(repos, Torrent(torrent_id=2, title="B.S01.1080p", imdb_link="ttB", quality=Quality.HD, is_show=True))
        _save(repos, Torrent(torrent_id=3, title="C.S01.1080p", imdb_link="ttC", quality=Quality.HD, is_show=True))

        _process(fake_config).process()
        assert len(repos.show.get_all()) == 3
        assert len(repos.show_season.get_all()) == 3

    def test_mixed_movies_and_shows(self, fake_config, repos):
        # Movie + show with same imdb_link group should not interfere
        _save(repos, Torrent(torrent_id=1, title="Movie.2020.1080p", imdb_link="ttM", quality=Quality.HD, is_show=False))
        _save(repos, Torrent(torrent_id=2, title="Show.S01.1080p", imdb_link="ttS", quality=Quality.HD, is_show=True))

        _process(fake_config).process()
        assert len(repos.movie.get_all()) == 1
        assert len(repos.show.get_all()) == 1
        assert len(repos.show_season.get_all()) == 1
