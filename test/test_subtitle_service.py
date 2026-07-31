"""Tests for src/subtitle_service.py and the SubtitleDownloadRepository."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from database.db import SubtitleDownloadRepository
from models.movie import Movie
from models.show import Show
from models.show_season import ShowSeason
from models.subtitle_download import SubtitleDownload
from models.torrent import Quality, Torrent
from subtitle_service import SubtitleUpdateService, extract_imdb_id


# ── Fixtures / fakes ─────────────────────────────────────────────────────────

class FakeJellyfin:
    """In-memory stand-in for JellyfinApi used by the subtitle service."""

    def __init__(self, movies=None, series=None, episodes=None, search_results=None):
        self.movies = movies or []
        self.series = series or []
        # {series_id: [episode dicts]}
        self.episodes = episodes or {}
        # default remote-search results returned for any item
        self.search_results = (
            search_results
            if search_results is not None
            else [{"Id": "sub-1", "DownloadCount": 10, "CommunityRating": 8.0}]
        )
        self.downloaded: list[tuple[str, str]] = []

    def fetch_library_items(self, item_types, fields="", page_size=200):
        if item_types == "Movie":
            return self.movies
        if item_types == "Series":
            return self.series
        return []

    def fetch_series_episodes(self, series_id, fields=""):
        return self.episodes.get(series_id, [])

    def search_remote_subtitles(self, item_id, language):
        return list(self.search_results)

    def download_remote_subtitle(self, item_id, subtitle_id):
        self.downloaded.append((item_id, subtitle_id))
        return True

    @staticmethod
    def item_has_subtitle_language(item, language):
        from jellyfin_api.jellyfin_api import JellyfinApi
        return JellyfinApi.item_has_subtitle_language(item, language)


@pytest.fixture
def subtitle_repo(engine):
    return SubtitleDownloadRepository(engine=engine)


def _make_service(fake_config, subtitle_repo, fake_jellyfin):
    fake_config.subtitle_source_language = "ENG"
    fake_config.subtitle_target_language = "hun"
    fake_config.subtitle_daily_limit = 1000
    fake_config.subtitle_download_repository = subtitle_repo

    service = SubtitleUpdateService(config=fake_config)
    service.jellyfin = fake_jellyfin
    return service


# ── extract_imdb_id ──────────────────────────────────────────────────────────

class TestExtractImdbId:
    def test_from_url(self):
        assert extract_imdb_id("https://www.imdb.com/title/tt0257290/?ref_=x") == "tt0257290"

    def test_none_and_missing(self):
        assert extract_imdb_id(None) is None
        assert extract_imdb_id("no id here") is None


# ── helpers ──────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_season_numbers_single(self):
        assert SubtitleUpdateService._season_numbers(2, -1) == {2}

    def test_season_numbers_range(self):
        assert SubtitleUpdateService._season_numbers(1, 3) == {1, 2, 3}

    def test_season_numbers_invalid(self):
        assert SubtitleUpdateService._season_numbers(-1, -1) == set()

    def test_pick_best_prefers_hash_match(self):
        results = [
            {"Id": "a", "DownloadCount": 100, "CommunityRating": 5.0},
            {"Id": "b", "DownloadCount": 1, "IsHashMatch": True},
        ]
        assert SubtitleUpdateService._pick_best(results)["Id"] == "b"

    def test_pick_best_by_download_count(self):
        results = [
            {"Id": "a", "DownloadCount": 100},
            {"Id": "b", "DownloadCount": 500},
        ]
        assert SubtitleUpdateService._pick_best(results)["Id"] == "b"

    def test_index_by_imdb(self):
        items = [
            {"Id": "1", "ProviderIds": {"Imdb": "tt1"}},
            {"Id": "2", "ProviderIds": {"Tmdb": "9"}},
        ]
        index = SubtitleUpdateService._index_by_imdb(items)
        assert index == {"tt1": {"Id": "1", "ProviderIds": {"Imdb": "tt1"}}}


# ── run() end to end ─────────────────────────────────────────────────────────

class TestRun:
    def test_downloads_movie_and_episodes(self, fake_config, repos, subtitle_repo):
        # English movie
        movie_torrent = repos.torrent.save(
            Torrent(torrent_id=1, imdb_link="https://imdb.com/title/tt1000/", language="ENG", is_show=False)
        )
        repos.movie.save(Movie(torrent_id=movie_torrent.id))

        # English show, season 1
        show_torrent = repos.torrent.save(
            Torrent(torrent_id=2, imdb_link="https://imdb.com/title/tt2000/", language="ENG", is_show=True)
        )
        show = repos.show.save(Show(imdb_link="https://imdb.com/title/tt2000/"))
        repos.show_season.save(ShowSeason(torrent_id=show_torrent.id, season=1, season_to=-1, show_id=show.id))

        fake = FakeJellyfin(
            movies=[{"Id": "m1", "Name": "A Movie", "ProviderIds": {"Imdb": "tt1000"}}],
            series=[{"Id": "s1", "Name": "A Show", "ProviderIds": {"Imdb": "tt2000"}}],
            episodes={
                "s1": [
                    {"Id": "e1", "Name": "S1E1", "ParentIndexNumber": 1},
                    {"Id": "e2", "Name": "S1E2", "ParentIndexNumber": 1},
                    {"Id": "e3", "Name": "S2E1", "ParentIndexNumber": 2},  # excluded season
                ]
            },
        )
        service = _make_service(fake_config, subtitle_repo, fake)

        stats = service.run()

        assert stats["downloaded"] == 3  # movie + 2 season-1 episodes
        downloaded_ids = {item_id for item_id, _ in fake.downloaded}
        assert downloaded_ids == {"m1", "e1", "e2"}

        # torrent_id is persisted so the tables can be cross-checked later
        assert subtitle_repo.get_by_item_id("m1").torrent_id == movie_torrent.id
        assert subtitle_repo.get_by_item_id("e1").torrent_id == show_torrent.id
        assert subtitle_repo.get_by_item_id("e2").torrent_id == show_torrent.id

    def test_skips_already_recorded(self, fake_config, repos, subtitle_repo):
        movie_torrent = repos.torrent.save(
            Torrent(torrent_id=1, imdb_link="https://imdb.com/title/tt1000/", language="ENG", is_show=False)
        )
        repos.movie.save(Movie(torrent_id=movie_torrent.id))
        subtitle_repo.save(
            SubtitleDownload(jellyfin_item_id="m1", status="downloaded", downloaded_at=datetime.utcnow())
        )

        fake = FakeJellyfin(
            movies=[{"Id": "m1", "Name": "A Movie", "ProviderIds": {"Imdb": "tt1000"}}],
        )
        service = _make_service(fake_config, subtitle_repo, fake)

        stats = service.run()

        assert stats["skipped"] == 1
        assert stats["downloaded"] == 0
        assert fake.downloaded == []

    def test_skips_item_with_existing_subtitle(self, fake_config, repos, subtitle_repo):
        movie_torrent = repos.torrent.save(
            Torrent(torrent_id=1, imdb_link="https://imdb.com/title/tt1000/", language="ENG", is_show=False)
        )
        repos.movie.save(Movie(torrent_id=movie_torrent.id))

        fake = FakeJellyfin(
            movies=[{
                "Id": "m1", "Name": "A Movie", "ProviderIds": {"Imdb": "tt1000"},
                "MediaStreams": [{"Type": "Subtitle", "Language": "hun"}],
            }],
        )
        service = _make_service(fake_config, subtitle_repo, fake)

        stats = service.run()

        assert stats["already_present"] == 1
        assert fake.downloaded == []

    def test_respects_daily_limit(self, fake_config, repos, subtitle_repo):
        for i in range(3):
            t = repos.torrent.save(
                Torrent(torrent_id=i + 1, imdb_link=f"https://imdb.com/title/tt100{i}/", language="ENG", is_show=False)
            )
            repos.movie.save(Movie(torrent_id=t.id))

        fake = FakeJellyfin(
            movies=[
                {"Id": f"m{i}", "Name": f"M{i}", "ProviderIds": {"Imdb": f"tt100{i}"}}
                for i in range(3)
            ],
        )
        service = _make_service(fake_config, subtitle_repo, fake)
        service.daily_limit = 2

        stats = service.run()

        assert stats["downloaded"] == 2
        assert stats["limit_reached"] is True
        assert len(fake.downloaded) == 2

    def test_no_results_marks_not_found(self, fake_config, repos, subtitle_repo):
        t = repos.torrent.save(
            Torrent(torrent_id=1, imdb_link="https://imdb.com/title/tt1000/", language="ENG", is_show=False)
        )
        repos.movie.save(Movie(torrent_id=t.id))

        fake = FakeJellyfin(
            movies=[{"Id": "m1", "Name": "A Movie", "ProviderIds": {"Imdb": "tt1000"}}],
            search_results=[],
        )
        service = _make_service(fake_config, subtitle_repo, fake)

        stats = service.run()

        assert stats["not_found"] == 1
        assert subtitle_repo.get_by_item_id("m1").status == "not_found"

    def test_hun_only_ignores_non_english(self, fake_config, repos, subtitle_repo):
        t = repos.torrent.save(
            Torrent(torrent_id=1, imdb_link="https://imdb.com/title/tt1000/", language="HUN", is_show=False)
        )
        repos.movie.save(Movie(torrent_id=t.id))

        fake = FakeJellyfin(
            movies=[{"Id": "m1", "Name": "A Movie", "ProviderIds": {"Imdb": "tt1000"}}],
        )
        service = _make_service(fake_config, subtitle_repo, fake)

        stats = service.run()

        assert stats["processed"] == 0
        assert fake.downloaded == []


# ── SubtitleDownloadRepository ───────────────────────────────────────────────

class TestSubtitleDownloadRepository:
    def test_upsert_inserts_then_updates(self, subtitle_repo):
        subtitle_repo.upsert(SubtitleDownload(jellyfin_item_id="x", status="not_found"))
        subtitle_repo.upsert(
            SubtitleDownload(jellyfin_item_id="x", status="downloaded", downloaded_at=datetime.utcnow())
        )
        rec = subtitle_repo.get_by_item_id("x")
        assert rec.status == "downloaded"

    def test_count_downloaded_since(self, subtitle_repo):
        now = datetime.utcnow()
        subtitle_repo.save(
            SubtitleDownload(jellyfin_item_id="a", status="downloaded", downloaded_at=now)
        )
        subtitle_repo.save(
            SubtitleDownload(jellyfin_item_id="b", status="downloaded", downloaded_at=now - timedelta(days=2))
        )
        subtitle_repo.save(SubtitleDownload(jellyfin_item_id="c", status="not_found"))

        assert subtitle_repo.count_downloaded_since(now - timedelta(days=1)) == 1
