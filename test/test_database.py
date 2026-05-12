"""Tests for the repository layer in src/database/db.py."""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel

from database.db import (
    BaseRepository,
    LocalFilesRepository,
    MovieRepository,
    ShowRepository,
    ShowSeasonsRepository,
    TorrentRepository,
    _create_engine,
    get_session,
    init_db,
)
from models.local_file_information import LocalFileInformation
from models.movie import Movie
from models.show import Show
from models.show_season import ShowSeason
from models.torrent import Quality, Torrent


# ── BaseRepository CRUD ──────────────────────────────────────────────────────

class TestBaseRepository:
    def test_save_and_get(self, repos):
        t = repos.torrent.save(Torrent(torrent_id=1, title="x"))
        fetched = repos.torrent.get(t.id)
        assert fetched.torrent_id == 1
        assert fetched.title == "x"

    def test_get_missing_returns_none(self, repos):
        assert repos.torrent.get(999) is None

    def test_get_all(self, repos):
        repos.torrent.save(Torrent(torrent_id=1, title="a"))
        repos.torrent.save(Torrent(torrent_id=2, title="b"))
        all_t = repos.torrent.get_all()
        assert len(all_t) == 2

    def test_get_all_offset(self, repos):
        for i in range(3):
            repos.torrent.save(Torrent(torrent_id=i, title=str(i)))
        rows = repos.torrent.get_all(offset=1)
        assert len(rows) == 2

    def test_find_by(self, repos):
        repos.torrent.save(Torrent(torrent_id=1, title="hd", category="HD"))
        repos.torrent.save(Torrent(torrent_id=2, title="sd", category="SD"))
        results = repos.torrent.find_by(category="HD")
        assert len(results) == 1
        assert results[0].title == "hd"

    def test_find_first_by_returns_none(self, repos):
        assert repos.torrent.find_first_by(category="missing") is None

    def test_find_first_by_returns_match(self, repos):
        repos.torrent.save(Torrent(torrent_id=1, title="hd", category="HD"))
        rec = repos.torrent.find_first_by(category="HD")
        assert rec is not None
        assert rec.title == "hd"

    def test_iter_chunks(self, repos):
        for i in range(5):
            repos.torrent.save(Torrent(torrent_id=i, title=str(i)))
        rows = list(repos.torrent.iter_chunks(chunk_size=2))
        assert len(rows) == 5

    def test_save_many(self, repos):
        repos.torrent.save_many(
            [Torrent(torrent_id=i, title=str(i)) for i in range(3)]
        )
        assert len(repos.torrent.get_all()) == 3

    def test_upsert_many_inserts_new(self, repos):
        repos.torrent.upsert_many(
            [Torrent(torrent_id=10, title="new")],
        )
        assert repos.torrent.find_first_by(torrent_id=10).title == "new"

    def test_upsert_many_updates_existing(self, repos):
        existing = repos.torrent.save(Torrent(torrent_id=10, title="old"))
        existing.title = "updated"
        repos.torrent.upsert_many([existing])
        assert repos.torrent.get(existing.id).title == "updated"

    def test_delete(self, repos):
        t = repos.torrent.save(Torrent(torrent_id=1, title="x"))
        repos.torrent.delete(t)
        assert repos.torrent.get(t.id) is None

    def test_delete_by_id_returns_true(self, repos):
        t = repos.torrent.save(Torrent(torrent_id=1, title="x"))
        assert repos.torrent.delete_by_id(t.id) is True

    def test_delete_by_id_missing_returns_false(self, repos):
        assert repos.torrent.delete_by_id(999) is False


# ── TorrentRepository specifics ──────────────────────────────────────────────

class TestTorrentRepository:
    def test_save_new_only_inserts_only_new(self, repos, capsys):
        repos.torrent.save(Torrent(torrent_id=1, title="exists"))
        repos.torrent.save_new_only(
            [
                Torrent(torrent_id=1, title="dup"),       # skipped
                Torrent(torrent_id=2, title="brand new"), # inserted
            ]
        )
        all_t = repos.torrent.get_all()
        titles = sorted(t.title for t in all_t)
        assert titles == ["brand new", "exists"]

    def test_save_new_only_no_records(self, repos, capsys):
        repos.torrent.save(Torrent(torrent_id=1, title="exists"))
        repos.torrent.save_new_only([Torrent(torrent_id=1, title="dup")])
        assert len(repos.torrent.get_all()) == 1

    def test_find_by_imdb_id_match(self, repos):
        repos.torrent.save(
            Torrent(
                torrent_id=1,
                title="x",
                imdb_link="https://www.imdb.com/title/tt1234567/",
            )
        )
        assert repos.torrent.find_by_imdb_id("tt1234567") is not None

    def test_find_by_imdb_id_no_match(self, repos):
        assert repos.torrent.find_by_imdb_id("tt9999999") is None

    def test_find_registered_media_movie(self, repos):
        t = repos.torrent.save(
            Torrent(torrent_id=1, title="x", imdb_link="tt1111111")
        )
        repos.movie.save(Movie(torrent_id=t.id))
        assert repos.torrent.find_registered_media_by_imdb_id("tt1111111") is not None

    def test_find_registered_media_show(self, repos):
        t = repos.torrent.save(
            Torrent(torrent_id=1, title="x", imdb_link="tt2222222")
        )
        repos.show_season.save(ShowSeason(torrent_id=t.id, season=1))
        assert repos.torrent.find_registered_media_by_imdb_id("tt2222222") is not None

    def test_find_registered_media_unregistered(self, repos):
        repos.torrent.save(
            Torrent(torrent_id=1, title="x", imdb_link="tt3333333")
        )
        # not linked to either Movie or ShowSeason
        assert repos.torrent.find_registered_media_by_imdb_id("tt3333333") is None


# ── Movie / ShowSeason / Show / LocalFiles specifics ─────────────────────────

class TestMovieRepository:
    def test_delete_by_torrent_id_found(self, repos):
        t = repos.torrent.save(Torrent(torrent_id=1, title="x"))
        repos.movie.save(Movie(torrent_id=t.id))
        assert repos.movie.delete_by_torrent_id(t.id) is True

    def test_delete_by_torrent_id_missing(self, repos):
        assert repos.movie.delete_by_torrent_id(123) is False


class TestShowSeasonsRepository:
    def test_get_all_seasons_for_show(self, repos):
        repos.show_season.save(ShowSeason(torrent_id=1, season=1, show_id=10))
        repos.show_season.save(ShowSeason(torrent_id=2, season=2, show_id=10))
        repos.show_season.save(ShowSeason(torrent_id=3, season=1, show_id=99))
        rows = repos.show_season.get_all_seasons_for_show(10)
        assert len(rows) == 2

    def test_delete_by_torrent_id_found(self, repos):
        ss = repos.show_season.save(ShowSeason(torrent_id=1, season=1, show_id=1))
        assert repos.show_season.delete_by_torrent_id(1) is True

    def test_delete_by_torrent_id_missing(self, repos):
        assert repos.show_season.delete_by_torrent_id(404) is False


class TestLocalFilesRepository:
    def test_save_if_new_inserts_then_skips_dup(self, repos):
        repos.local_files.save_if_new(
            LocalFileInformation(torrent_id=1, torrent_file_local_path="a.torrent")
        )
        repos.local_files.save_if_new(
            LocalFileInformation(torrent_id=1, torrent_file_local_path="b.torrent")
        )
        rows = repos.local_files.get_all()
        assert len(rows) == 1
        assert rows[0].torrent_file_local_path == "a.torrent"


# ── Misc engine helpers ──────────────────────────────────────────────────────

def test_init_db_creates_tables():
    eng = _create_engine("sqlite:///:memory:")
    init_db(eng)
    # All five tables should now exist
    with Session(eng) as s:
        # If the tables exist these queries should not raise
        s.exec(__import__("sqlmodel").select(Torrent)).all()
        s.exec(__import__("sqlmodel").select(Movie)).all()
        s.exec(__import__("sqlmodel").select(Show)).all()
        s.exec(__import__("sqlmodel").select(ShowSeason)).all()
        s.exec(__import__("sqlmodel").select(LocalFileInformation)).all()


def test_get_session_rollbacks_on_exception(engine):
    with pytest.raises(RuntimeError):
        with get_session(engine) as session:
            session.add(Torrent(torrent_id=999, title="should-rollback"))
            raise RuntimeError("boom")

    repo = TorrentRepository(engine=engine)
    assert repo.find_first_by(torrent_id=999) is None
