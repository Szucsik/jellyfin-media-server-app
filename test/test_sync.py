"""Tests for src/sync.py — heavy emphasis on TV show flows."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from database.db import (
    LocalFilesRepository,
    MovieRepository,
    ShowRepository,
    ShowSeasonsRepository,
    TorrentRepository,
)
from models.local_file_information import LocalFileInformation
from models.show import Show
from models.show_season import ShowSeason
from models.torrent import Quality, Torrent
from sync import (
    MediaDownloadRequest,
    TorrentSyncService,
    extract_imdb_id,
    extract_imdb_id_from_url,
)


# A thread-safe in-memory SQLite engine — needed because TorrentSyncService
# offloads DB queries to a ThreadPoolExecutor via loop.run_in_executor and
# the default in-memory pool isn't shared across threads.
@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def repos(engine):
    return type(
        "Repos",
        (),
        {
            "torrent": TorrentRepository(engine=engine),
            "movie": MovieRepository(engine=engine),
            "show": ShowRepository(engine=engine),
            "show_season": ShowSeasonsRepository(engine=engine),
            "local_files": LocalFilesRepository(engine=engine),
        },
    )()


# ═════════════════════════════════════════════════════════════════════════════
#  Module-level helpers
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractImdbId:
    def test_extracts_from_jellyfin_path(self):
        assert extract_imdb_id("/media/movies/My Movie [imdbid-tt1234567]/MyMovie.mkv") == "tt1234567"

    def test_returns_none_when_missing(self):
        assert extract_imdb_id("/media/movies/no-imdb/MyMovie.mkv") is None

    def test_extracts_from_show_path_with_season(self):
        path = "/media/series/Some Show [imdbid-tt9999999]/Season 1/Some Show S01E03.mkv"
        assert extract_imdb_id(path) == "tt9999999"


class TestExtractImdbIdFromUrl:
    def test_extracts_from_imdb_url(self):
        assert extract_imdb_id_from_url("https://www.imdb.com/title/tt0257290/?ref_=fn_t_1") == "tt0257290"

    def test_returns_none_when_missing(self):
        assert extract_imdb_id_from_url("not an imdb link") is None


# ═════════════════════════════════════════════════════════════════════════════
#  Fixtures & helpers
# ═════════════════════════════════════════════════════════════════════════════

def _make_service(fake_config) -> TorrentSyncService:
    # JellyfinApi constructor only needs valid api_key + user_id (set in fake_config)
    return TorrentSyncService(fake_config)


def _save_show_torrent(
    repos,
    *,
    title="Show.S01.1080p",
    imdb="tt1111111",
    torrent_id=1001,
) -> Torrent:
    return repos.torrent.save(
        Torrent(
            title=title,
            imdb_link=f"https://imdb.com/title/{imdb}/",
            quality=Quality.HD,
            is_show=True,
            torrent_id=torrent_id,
        )
    )


def _save_movie_torrent(
    repos,
    *,
    title="Movie.1080p",
    imdb="tt2222222",
    torrent_id=2001,
) -> Torrent:
    return repos.torrent.save(
        Torrent(
            title=title,
            imdb_link=f"https://imdb.com/title/{imdb}/",
            quality=Quality.HD,
            is_show=False,
            torrent_id=torrent_id,
        )
    )


def _save_local_info(repos, torrent: Torrent, **kwargs) -> LocalFileInformation:
    return repos.local_files.save(
        LocalFileInformation(
            torrent_id=torrent.id,
            torrent_file_local_path=kwargs.get("torrent_file_local_path", f"/torrents/{torrent.id}.torrent"),
            main_media_files_local_path=kwargs.get("main_media_files_local_path", ""),
            original_file_path=kwargs.get("original_file_path", "ep.mkv"),
            symlink_path=kwargs.get("symlink_path", "/media/series/x/Season 1/ep.mkv"),
        )
    )


# ═════════════════════════════════════════════════════════════════════════════
#  _find_episode_index
# ═════════════════════════════════════════════════════════════════════════════

class TestFindEpisodeIndex:
    def test_exact_path_match(self, fake_config):
        svc = _make_service(fake_config)
        info = LocalFileInformation(
            torrent_id=1,
            symlink_path="/a/Show/Season 1/E01.mkv;/a/Show/Season 1/E02.mkv;/a/Show/Season 1/E03.mkv",
            original_file_path="E01.mkv;E02.mkv;E03.mkv",
        )
        assert svc._find_episode_index("/a/Show/Season 1/E02.mkv", info) == 1

    def test_filename_fallback(self, fake_config):
        svc = _make_service(fake_config)
        info = LocalFileInformation(
            torrent_id=1,
            symlink_path="/old/E01.mkv;/old/E02.mkv",
            original_file_path="E01.mkv;E02.mkv",
        )
        # User played path has different prefix but same filename
        assert svc._find_episode_index("/new/E02.mkv", info) == 1

    def test_defaults_to_zero_when_no_match(self, fake_config):
        svc = _make_service(fake_config)
        info = LocalFileInformation(
            torrent_id=1,
            symlink_path="/x/E01.mkv;/x/E02.mkv",
            original_file_path="E01.mkv;E02.mkv",
        )
        assert svc._find_episode_index("/x/E99.mkv", info) == 0


# ═════════════════════════════════════════════════════════════════════════════
#  _find_qbt_file_index
# ═════════════════════════════════════════════════════════════════════════════

class TestFindQbtFileIndex:
    def test_exact_path_match(self, fake_config):
        svc = _make_service(fake_config)
        files = [
            {"name": "Show/Season 1/E01.mkv", "index": 0},
            {"name": "Show/Season 1/E02.mkv", "index": 1},
        ]
        assert svc._find_qbt_file_index(files, "Show/Season 1/E02.mkv") == 1

    def test_endswith_match(self, fake_config):
        svc = _make_service(fake_config)
        files = [{"name": "root/Show/E01.mkv", "index": 0}]
        assert svc._find_qbt_file_index(files, "Show/E01.mkv") == 0

    def test_filename_fallback(self, fake_config):
        svc = _make_service(fake_config)
        files = [
            {"name": "weird/path/E01.mkv", "index": 0},
            {"name": "weird/path/E07.mkv", "index": 7},
        ]
        assert svc._find_qbt_file_index(files, "totally/different/E07.mkv") == 7

    def test_returns_none_when_not_found(self, fake_config):
        svc = _make_service(fake_config)
        files = [{"name": "a.mkv", "index": 0}]
        assert svc._find_qbt_file_index(files, "missing.mkv") is None


# ═════════════════════════════════════════════════════════════════════════════
#  Symlink helpers
# ═════════════════════════════════════════════════════════════════════════════

class TestUpdateSingleSymlink:
    def test_replaces_existing_symlink_with_downloaded_file(self, fake_config, tmp_path):
        svc = _make_service(fake_config)

        # Set up a downloaded real file
        downloaded_root = Path(fake_config.downloaded_target_directory)
        rel = "Show/Season 1/E01.mkv"
        real_file = downloaded_root / rel
        real_file.parent.mkdir(parents=True, exist_ok=True)
        real_file.write_bytes(b"x")

        # Existing placeholder symlink
        symlink = tmp_path / "E01.mkv"
        symlink.symlink_to(Path(fake_config.placeholder_starter_path))

        svc._update_single_symlink(
            save_path=fake_config.downloaded_directory,
            original_file=rel,
            symlink_str=str(symlink),
        )

        assert symlink.is_symlink()
        assert symlink.resolve() == real_file.resolve()

    def test_translates_downloaded_directory_paths(self, fake_config, tmp_path):
        """save_path on the qBittorrent side must be translated to container side."""
        svc = _make_service(fake_config)
        # Pretend qBittorrent reports a different daemon-side path
        fake_config.downloaded_directory = "/qbt/downloads"
        target = Path(fake_config.downloaded_target_directory)
        rel = "Show/E01.mkv"
        real = target / rel
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_bytes(b"y")

        symlink = tmp_path / "E01.mkv"
        symlink.symlink_to(Path(fake_config.placeholder_starter_path))

        svc._update_single_symlink(
            save_path="/qbt/downloads",
            original_file=rel,
            symlink_str=str(symlink),
        )
        assert symlink.resolve() == real.resolve()

    def test_skips_when_downloaded_file_missing(self, fake_config, tmp_path):
        svc = _make_service(fake_config)
        symlink = tmp_path / "x.mkv"
        symlink.symlink_to(Path(fake_config.placeholder_starter_path))
        before = symlink.resolve()

        svc._update_single_symlink(
            save_path=fake_config.downloaded_directory,
            original_file="nothing/here.mkv",
            symlink_str=str(symlink),
        )
        # Symlink unchanged
        assert symlink.resolve() == before


class TestUpdateSymlinks:
    def test_updates_all_files_in_order(self, fake_config, tmp_path):
        svc = _make_service(fake_config)
        target = Path(fake_config.downloaded_target_directory)

        files = ["S/E01.mkv", "S/E02.mkv", "S/E03.mkv"]
        for f in files:
            p = target / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"d")

        symlinks = []
        for i in range(3):
            link = tmp_path / f"E0{i+1}.mkv"
            link.symlink_to(Path(fake_config.placeholder_starter_path))
            symlinks.append(link)

        info = LocalFileInformation(
            torrent_id=1,
            symlink_path=";".join(str(s) for s in symlinks),
            original_file_path=";".join(files),
        )

        svc._update_symlinks(info, fake_config.downloaded_directory)

        for sym, f in zip(symlinks, files):
            assert sym.resolve() == (target / f).resolve()

    def test_mismatched_lengths_logs_and_returns(self, fake_config, tmp_path):
        svc = _make_service(fake_config)
        info = LocalFileInformation(
            torrent_id=1,
            symlink_path="a;b",
            original_file_path="a",  # 1 element vs 2
        )
        # Should not raise
        svc._update_symlinks(info, fake_config.downloaded_directory)

    def test_empty_paths_short_circuit(self, fake_config):
        svc = _make_service(fake_config)
        info = LocalFileInformation(torrent_id=1, symlink_path="", original_file_path="")
        svc._update_symlinks(info, fake_config.downloaded_directory)


# ═════════════════════════════════════════════════════════════════════════════
#  _process_played_item
# ═════════════════════════════════════════════════════════════════════════════

class TestProcessPlayedItem:
    def test_ignores_item_without_path(self, fake_config):
        svc = _make_service(fake_config)
        asyncio.run(svc._process_played_item({"NowPlayingItem": {}}))
        assert svc._media_download_queue.empty()

    def test_ignores_item_without_imdb_id(self, fake_config):
        svc = _make_service(fake_config)
        asyncio.run(svc._process_played_item({"NowPlayingItem": {"Path": "/random/no-imdb.mkv"}}))
        assert svc._media_download_queue.empty()

    def test_ignores_when_no_torrent_in_db(self, fake_config):
        svc = _make_service(fake_config)
        asyncio.run(svc._process_played_item({
            "NowPlayingItem": {"Path": "/media/m [imdbid-tt0000000]/m.mkv"},
        }))
        assert svc._media_download_queue.empty()

    def test_movie_request_is_queued_on_first_play(self, fake_config, repos):
        """First play of a movie is enqueued and recorded as in-flight."""
        svc = _make_service(fake_config)
        torrent = _save_movie_torrent(repos, imdb="tt5000001", torrent_id=5001)
        repos.movie.save(__import__("models.movie", fromlist=["Movie"]).Movie(torrent_id=torrent.id))
        _save_local_info(
            repos, torrent,
            original_file_path="movie.mkv",
            symlink_path="/media/movies/m [imdbid-tt5000001]/movie.mkv",
        )

        item = {
            "NowPlayingItem": {
                "Path": "/media/movies/m [imdbid-tt5000001]/movie.mkv",
                "Id": "jf-001",
            },
        }
        asyncio.run(svc._process_played_item(item))

        assert svc._media_download_queue.qsize() == 1
        assert ("jf-001", 0) in svc._inflight_keys

    def test_movie_repeated_clicks_remain_suppressed(self, fake_config, repos):
        svc = _make_service(fake_config)
        torrent = _save_movie_torrent(repos, imdb="tt5000002", torrent_id=5002)
        repos.movie.save(__import__("models.movie", fromlist=["Movie"]).Movie(torrent_id=torrent.id))
        _save_local_info(repos, torrent, symlink_path="/media/movies/m [imdbid-tt5000002]/m.mkv")

        item = {"NowPlayingItem": {"Path": "/media/movies/m [imdbid-tt5000002]/m.mkv", "Id": "x"}}
        asyncio.run(svc._process_played_item(item))
        asyncio.run(svc._process_played_item(item))
        # First call queued; second call deduped via _inflight_keys.
        assert svc._media_download_queue.qsize() == 1

    def test_show_request_resolves_episode_index_and_show_season(self, fake_config, repos):
        svc = _make_service(fake_config)
        torrent = _save_show_torrent(repos, imdb="tt7000001", torrent_id=7001)
        season = repos.show_season.save(
            ShowSeason(torrent_id=torrent.id, season=1, season_to=1, show_id=42),
        )
        _save_local_info(
            repos, torrent,
            original_file_path="S/E01.mkv;S/E02.mkv;S/E03.mkv",
            symlink_path=(
                "/media/series/S [imdbid-tt7000001]/Season 1/E01.mkv;"
                "/media/series/S [imdbid-tt7000001]/Season 1/E02.mkv;"
                "/media/series/S [imdbid-tt7000001]/Season 1/E03.mkv"
            ),
        )

        item = {
            "NowPlayingItem": {
                "Path": "/media/series/S [imdbid-tt7000001]/Season 1/E02.mkv",
                "Id": "jf-ep2",
            },
        }
        asyncio.run(svc._process_played_item(item))

        assert svc._media_download_queue.qsize() == 1
        req = svc._media_download_queue.get_nowait()
        assert req.episode_file_index == 1
        assert req.show_season is not None
        assert req.show_season.show_id == 42
        assert req.torrent.is_show is True

    def test_show_new_episode_sets_interrupt_when_already_downloading(self, fake_config, repos):
        svc = _make_service(fake_config)
        torrent = _save_show_torrent(repos, imdb="tt7000002", torrent_id=7002)
        repos.show_season.save(
            ShowSeason(torrent_id=torrent.id, season=1, season_to=1, show_id=99),
        )
        _save_local_info(
            repos, torrent,
            original_file_path="E01.mkv;E02.mkv",
            symlink_path="/media/series/x [imdbid-tt7000002]/Season 1/E01.mkv;"
                        "/media/series/x [imdbid-tt7000002]/Season 1/E02.mkv",
        )

        # Simulate an active request for the same show.
        current_request = MediaDownloadRequest(
            imdb_id="tt7000002",
            played_path="/old.mkv",
            jellyfin_item_id="old",
            torrent=torrent,
            local_info=LocalFileInformation(),
            episode_file_index=0,
        )
        interrupt_event = asyncio.Event()
        svc._show_current_requests["tt7000002"] = current_request
        svc._show_interrupt_events["tt7000002"] = interrupt_event

        assert not interrupt_event.is_set()
        item = {
            "NowPlayingItem": {
                "Path": "/media/series/x [imdbid-tt7000002]/Season 1/E02.mkv",
                "Id": "jf-ep2",
            },
        }
        asyncio.run(svc._process_played_item(item))
        assert interrupt_event.is_set()
        assert svc._media_download_queue.empty()
        pending = svc._pending_show_requests["tt7000002"]
        assert pending.episode_file_index == 1

    def test_show_new_episode_for_different_show_runs_in_parallel(self, fake_config, repos):
        svc = _make_service(fake_config)
        current_t = _save_show_torrent(repos, imdb="tt8000001", torrent_id=8001)
        other_t = _save_show_torrent(repos, imdb="tt8000002", torrent_id=8002)
        repos.show_season.save(
            ShowSeason(torrent_id=other_t.id, season=1, season_to=1, show_id=5),
        )
        _save_local_info(
            repos, other_t,
            original_file_path="E01.mkv",
            symlink_path="/media/series/o [imdbid-tt8000002]/Season 1/E01.mkv",
        )

        interrupt_event = asyncio.Event()
        svc._show_current_requests["tt8000001"] = MediaDownloadRequest(
            imdb_id="tt8000001",
            played_path="/cur.mkv",
            jellyfin_item_id="cur",
            torrent=current_t,
            local_info=LocalFileInformation(),
            episode_file_index=0,
        )
        svc._show_interrupt_events["tt8000001"] = interrupt_event

        item = {
            "NowPlayingItem": {
                "Path": "/media/series/o [imdbid-tt8000002]/Season 1/E01.mkv",
                "Id": "jf-ep1",
            },
        }
        asyncio.run(svc._process_played_item(item))
        assert not interrupt_event.is_set()
        assert svc._media_download_queue.qsize() == 1

    def test_ignores_when_local_info_missing(self, fake_config, repos):
        svc = _make_service(fake_config)
        torrent = _save_show_torrent(repos, imdb="tt9000001", torrent_id=9001)
        repos.show_season.save(
            ShowSeason(torrent_id=torrent.id, season=1, season_to=1, show_id=1),
        )
        # No LocalFileInformation saved!
        item = {"NowPlayingItem": {"Path": "/media/series/x [imdbid-tt9000001]/Season 1/E01.mkv", "Id": "x"}}
        asyncio.run(svc._process_played_item(item))
        assert svc._media_download_queue.empty()


# ═════════════════════════════════════════════════════════════════════════════
#  Movie download flow
# ═════════════════════════════════════════════════════════════════════════════

class TestMovieDownload:
    def test_handle_movie_download_refreshes_jellyfin_on_success(self, fake_config, repos, tmp_path):
        svc = _make_service(fake_config)
        torrent = _save_movie_torrent(repos, imdb="tt6000001", torrent_id=6001)

        # Set up a real downloaded file + a placeholder symlink
        target = Path(fake_config.downloaded_target_directory)
        rel = "movie.mkv"
        (target / rel).write_bytes(b"v")
        symlink = tmp_path / "movie.mkv"
        symlink.symlink_to(Path(fake_config.placeholder_starter_path))

        info = _save_local_info(
            repos, torrent,
            original_file_path=rel,
            symlink_path=str(symlink),
        )
        request = MediaDownloadRequest(
            imdb_id="tt6000001",
            played_path=str(symlink),
            jellyfin_item_id="jf-mov",
            torrent=torrent,
            local_info=info,
            episode_file_index=0,
        )

        svc.bittorrent.torrent_task = AsyncMock(return_value=fake_config.downloaded_directory)
        svc.jellyfin.refresh_item = MagicMock()

        asyncio.run(svc._handle_movie_download(request))

        svc.bittorrent.torrent_task.assert_awaited_once()
        call = svc.bittorrent.torrent_task.await_args
        assert callable(call.kwargs["on_placeholder_updated"])
        svc.jellyfin.refresh_item.assert_called_once_with("jf-mov")
        assert symlink.resolve() == (target / rel).resolve()

    def test_handle_movie_download_skips_refresh_on_empty_save_path(self, fake_config, repos):
        svc = _make_service(fake_config)
        torrent = _save_movie_torrent(repos, imdb="tt6000002", torrent_id=6002)
        info = _save_local_info(repos, torrent, symlink_path="/x/m.mkv")
        request = MediaDownloadRequest(
            imdb_id="tt6000002", played_path="/x/m.mkv", jellyfin_item_id="x",
            torrent=torrent, local_info=info, episode_file_index=0,
        )

        svc.bittorrent.torrent_task = AsyncMock(return_value="")
        svc.jellyfin.refresh_item = MagicMock()

        asyncio.run(svc._handle_movie_download(request))
        svc.jellyfin.refresh_item.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
#  Show download — Phase 1 (episode)
# ═════════════════════════════════════════════════════════════════════════════

def _make_show_request(fake_config, repos, *, imdb="tt7100001", torrent_id=7101,
                       n_episodes=3, played_index=1, show_id=10):
    torrent = _save_show_torrent(repos, imdb=imdb, torrent_id=torrent_id)
    season = repos.show_season.save(
        ShowSeason(torrent_id=torrent.id, season=1, season_to=1, show_id=show_id),
    )
    original_files = [f"S/E0{i+1}.mkv" for i in range(n_episodes)]
    symlinks = [f"/media/series/X/Season 1/E0{i+1}.mkv" for i in range(n_episodes)]
    info = _save_local_info(
        repos, torrent,
        original_file_path=";".join(original_files),
        symlink_path=";".join(symlinks),
    )
    return MediaDownloadRequest(
        imdb_id=imdb,
        played_path=symlinks[played_index],
        jellyfin_item_id=f"jf-{torrent_id}",
        torrent=torrent,
        local_info=info,
        episode_file_index=played_index,
        show_season=season,
    )


class TestPhaseEpisode:
    def test_sets_priorities_and_full_speed_and_refreshes(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos, n_episodes=3, played_index=1)

        torrent_files = [
            {"name": "S/E01.mkv", "index": 0, "size": 100, "progress": 0.0, "priority": 1},
            {"name": "S/E02.mkv", "index": 1, "size": 100, "progress": 0.0, "priority": 1},
            {"name": "S/E03.mkv", "index": 2, "size": 100, "progress": 0.0, "priority": 1},
        ]

        svc.bittorrent.add_torrent = AsyncMock(return_value="hash1")
        svc.bittorrent.get_torrent_files = AsyncMock(return_value=torrent_files)
        svc.bittorrent.set_file_priorities = AsyncMock()
        svc.bittorrent.set_download_limit = AsyncMock()
        svc.bittorrent.wait_for_files_complete = AsyncMock(return_value=True)
        svc.bittorrent.get_save_path = AsyncMock(return_value="")
        svc.jellyfin.refresh_item = MagicMock()

        result = asyncio.run(svc._phase_episode(request))

        assert result is True
        # All files set to 0, then the target file set to 7
        prio_calls = svc.bittorrent.set_file_priorities.await_args_list
        assert prio_calls[0].args == ("hash1", [0, 1, 2], 0)
        assert prio_calls[1].args == ("hash1", [1], 7)
        # Full speed
        from jellyfin_api.bittorrentapi import SPEED_UNLIMITED
        svc.bittorrent.set_download_limit.assert_awaited_once_with("hash1", SPEED_UNLIMITED)
        # Wait passed correct indices and interrupt event
        wait_call = svc.bittorrent.wait_for_files_complete.await_args
        assert wait_call.args[0] == "hash1"
        assert wait_call.args[1] == [1]
        assert wait_call.kwargs["symlink_paths"] == ["/media/series/X/Season 1/E02.mkv"]
        svc.jellyfin.refresh_item.assert_called_once_with(f"jf-{request.torrent.torrent_id}")

    def test_returns_true_when_qbt_file_missing_to_avoid_blocking(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos, n_episodes=2, played_index=0)

        # qBittorrent reports unrelated files
        torrent_files = [{"name": "different.mkv", "index": 0, "size": 1, "progress": 0, "priority": 1}]
        svc.bittorrent.add_torrent = AsyncMock(return_value="hash")
        svc.bittorrent.get_torrent_files = AsyncMock(return_value=torrent_files)

        # Original file is "S/E01.mkv" but torrent only has "different.mkv" with mismatched basename
        request.local_info.original_file_path = "S/missingep.mkv;S/E02.mkv"
        request.episode_file_index = 0

        result = asyncio.run(svc._phase_episode(request))
        # _phase_episode returns True so orchestrator moves on
        assert result is True

    def test_returns_false_when_interrupted(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos, n_episodes=2, played_index=0)

        svc.bittorrent.add_torrent = AsyncMock(return_value="hash")
        svc.bittorrent.get_torrent_files = AsyncMock(return_value=[
            {"name": "S/E01.mkv", "index": 0, "size": 1, "progress": 0, "priority": 1},
            {"name": "S/E02.mkv", "index": 1, "size": 1, "progress": 0, "priority": 1},
        ])
        svc.bittorrent.set_file_priorities = AsyncMock()
        svc.bittorrent.set_download_limit = AsyncMock()
        svc.bittorrent.wait_for_files_complete = AsyncMock(return_value=False)
        svc.jellyfin.refresh_item = MagicMock()

        result = asyncio.run(svc._phase_episode(request))
        assert result is False
        svc.jellyfin.refresh_item.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
#  Show download — Phase 2 (season)
# ═════════════════════════════════════════════════════════════════════════════

class TestPhaseSeason:
    def test_throttles_to_20mbps_and_enables_all_files(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos, n_episodes=3, played_index=0)

        svc.bittorrent.add_torrent = AsyncMock(return_value="h")
        svc.bittorrent.get_torrent_files = AsyncMock(return_value=[
            {"name": f"E0{i+1}.mkv", "index": i, "size": 1, "progress": 0, "priority": 1} for i in range(3)
        ])
        svc.bittorrent.set_file_priorities = AsyncMock()
        svc.bittorrent.set_download_limit = AsyncMock()
        svc.bittorrent.wait_for_files_complete = AsyncMock(return_value=True)
        svc.bittorrent.get_save_path = AsyncMock(return_value="")
        svc.jellyfin.refresh_item = MagicMock()

        result = asyncio.run(svc._phase_season(request))
        assert result is True

        from jellyfin_api.bittorrentapi import SPEED_160_MBPS
        prio_calls = svc.bittorrent.set_file_priorities.await_args_list
        assert prio_calls[0].args == ("h", [0, 1, 2], 0)
        assert prio_calls[1].args == ("h", [0, 1, 2], 1)
        svc.bittorrent.set_download_limit.assert_awaited_once_with("h", SPEED_160_MBPS)
        svc.jellyfin.refresh_item.assert_called_once()

    def test_interrupted_returns_false_and_no_refresh(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos, n_episodes=2, played_index=0)

        svc.bittorrent.add_torrent = AsyncMock(return_value="h")
        svc.bittorrent.get_torrent_files = AsyncMock(return_value=[
            {"name": "E01.mkv", "index": 0, "size": 1, "progress": 0, "priority": 1},
            {"name": "E02.mkv", "index": 1, "size": 1, "progress": 0, "priority": 1},
        ])
        svc.bittorrent.set_file_priorities = AsyncMock()
        svc.bittorrent.set_download_limit = AsyncMock()
        svc.bittorrent.wait_for_files_complete = AsyncMock(return_value=False)
        svc.jellyfin.refresh_item = MagicMock()

        result = asyncio.run(svc._phase_season(request))
        assert result is False
        svc.jellyfin.refresh_item.assert_not_called()

    def test_updates_only_target_season_symlinks(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos, n_episodes=4, played_index=1)
        request.local_info.symlink_path = ";".join([
            "/media/series/X/Season 1/E01.mkv",
            "/media/series/X/Season 1/E02.mkv",
            "/media/series/X/Season 2/E01.mkv",
            "/media/series/X/Season 2/E02.mkv",
        ])
        request.local_info.original_file_path = ";".join([
            "X/Season 1/E01.mkv",
            "X/Season 1/E02.mkv",
            "X/Season 2/E01.mkv",
            "X/Season 2/E02.mkv",
        ])

        svc.bittorrent.add_torrent = AsyncMock(return_value="h")
        svc.bittorrent.get_torrent_files = AsyncMock(return_value=[
            {"name": "X/Season 1/E01.mkv", "index": 0, "size": 1, "progress": 0, "priority": 1},
            {"name": "X/Season 1/E02.mkv", "index": 1, "size": 1, "progress": 0, "priority": 1},
            {"name": "X/Season 2/E01.mkv", "index": 2, "size": 1, "progress": 0, "priority": 1},
            {"name": "X/Season 2/E02.mkv", "index": 3, "size": 1, "progress": 0, "priority": 1},
        ])
        svc.bittorrent.set_file_priorities = AsyncMock()
        svc.bittorrent.set_download_limit = AsyncMock()
        svc.bittorrent.wait_for_files_complete = AsyncMock(return_value=True)
        svc.bittorrent.get_save_path = AsyncMock(return_value="/downloads")
        svc._update_selected_symlinks = MagicMock()
        svc.jellyfin.refresh_item = MagicMock()

        result = asyncio.run(svc._phase_season(request))

        assert result is True
        svc._update_selected_symlinks.assert_called_once_with(request.local_info, "/downloads", [0, 1])


# ═════════════════════════════════════════════════════════════════════════════
#  Show download — Phase 3 (other seasons)
# ═════════════════════════════════════════════════════════════════════════════

class TestPhaseShow:
    def test_skips_when_no_show_season(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos)
        request.show_season = None

        svc.bittorrent.add_torrent = AsyncMock()

        asyncio.run(svc._phase_show(request))
        svc.bittorrent.add_torrent.assert_not_called()

    def test_skips_when_only_one_season_exists(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos)

        svc.bittorrent.add_torrent = AsyncMock()
        asyncio.run(svc._phase_show(request))
        svc.bittorrent.add_torrent.assert_not_called()

    def test_downloads_other_seasons_at_5mbps_in_order(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(
            fake_config, repos, imdb="tt7200001", torrent_id=7201, show_id=77,
        )

        # Create 2 additional seasons for the same show
        s2_t = _save_show_torrent(repos, imdb="tt7200001", torrent_id=7202)
        s3_t = _save_show_torrent(repos, imdb="tt7200001", torrent_id=7203)
        repos.show_season.save(ShowSeason(torrent_id=s2_t.id, season=2, season_to=2, show_id=77))
        repos.show_season.save(ShowSeason(torrent_id=s3_t.id, season=3, season_to=3, show_id=77))
        _save_local_info(repos, s2_t, original_file_path="S2.mkv", symlink_path="/x/S2.mkv")
        _save_local_info(repos, s3_t, original_file_path="S3.mkv", symlink_path="/x/S3.mkv")

        svc.bittorrent.add_torrent = AsyncMock(side_effect=["h2", "h3"])
        svc.bittorrent.get_torrent_files = AsyncMock(side_effect=[
            [{"name": "S2.mkv", "index": 0, "size": 1, "progress": 0, "priority": 1}],
            [{"name": "S3.mkv", "index": 0, "size": 1, "progress": 0, "priority": 1}],
        ])
        svc.bittorrent.set_file_priorities = AsyncMock()
        svc.bittorrent.set_download_limit = AsyncMock()
        svc.bittorrent.wait_for_torrent_complete = AsyncMock(return_value=True)
        svc.bittorrent.get_save_path = AsyncMock(return_value="")
        svc.jellyfin.refresh_item = MagicMock()

        asyncio.run(svc._phase_show(request))

        from jellyfin_api.bittorrentapi import SPEED_20_MBPS
        # Both other seasons received a 20 Mbps throttle
        assert svc.bittorrent.set_download_limit.await_count == 2
        for call in svc.bittorrent.set_download_limit.await_args_list:
            assert call.args[1] == SPEED_20_MBPS
        assert svc.bittorrent.add_torrent.await_count == 2

    def test_excludes_currently_playing_season_from_phase3(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(
            fake_config, repos, imdb="tt7300001", torrent_id=7301, show_id=88,
        )
        # Other season exists
        other_t = _save_show_torrent(repos, imdb="tt7300001", torrent_id=7302)
        repos.show_season.save(ShowSeason(torrent_id=other_t.id, season=2, season_to=2, show_id=88))
        _save_local_info(repos, other_t, original_file_path="S2.mkv", symlink_path="/x/S2.mkv")

        svc.bittorrent.add_torrent = AsyncMock(return_value="hOther")
        svc.bittorrent.get_torrent_files = AsyncMock(return_value=[
            {"name": "S2.mkv", "index": 0, "size": 1, "progress": 0, "priority": 1},
        ])
        svc.bittorrent.set_file_priorities = AsyncMock()
        svc.bittorrent.set_download_limit = AsyncMock()
        svc.bittorrent.wait_for_torrent_complete = AsyncMock(return_value=True)
        svc.bittorrent.get_save_path = AsyncMock(return_value="")
        svc.jellyfin.refresh_item = MagicMock()

        asyncio.run(svc._phase_show(request))

        # Only the OTHER season torrent should be added
        svc.bittorrent.add_torrent.assert_awaited_once()
        call_arg = svc.bittorrent.add_torrent.await_args.args[0]
        # Must not be the request's own torrent file
        assert request.local_info.torrent_file_local_path not in call_arg

    def test_aborts_remaining_seasons_when_interrupted_mid_phase3(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(
            fake_config, repos, imdb="tt7400001", torrent_id=7401, show_id=200,
        )
        s2 = _save_show_torrent(repos, imdb="tt7400001", torrent_id=7402)
        s3 = _save_show_torrent(repos, imdb="tt7400001", torrent_id=7403)
        repos.show_season.save(ShowSeason(torrent_id=s2.id, season=2, season_to=2, show_id=200))
        repos.show_season.save(ShowSeason(torrent_id=s3.id, season=3, season_to=3, show_id=200))
        _save_local_info(repos, s2, original_file_path="S2.mkv", symlink_path="/x/S2.mkv")
        _save_local_info(repos, s3, original_file_path="S3.mkv", symlink_path="/x/S3.mkv")

        svc.bittorrent.add_torrent = AsyncMock(return_value="h")
        svc.bittorrent.get_torrent_files = AsyncMock(return_value=[
            {"name": "S2.mkv", "index": 0, "size": 1, "progress": 0, "priority": 1},
        ])
        svc.bittorrent.set_file_priorities = AsyncMock()
        svc.bittorrent.set_download_limit = AsyncMock()
        # First season interrupted
        svc.bittorrent.wait_for_torrent_complete = AsyncMock(return_value=False)
        svc.bittorrent.get_save_path = AsyncMock(return_value="")
        svc.jellyfin.refresh_item = MagicMock()

        asyncio.run(svc._phase_show(request))

        # Only one season attempted, then bailed
        assert svc.bittorrent.add_torrent.await_count == 1

    def test_skips_when_interrupt_already_set(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(
            fake_config, repos, imdb="tt7500001", torrent_id=7501, show_id=300,
        )
        other = _save_show_torrent(repos, imdb="tt7500001", torrent_id=7502)
        repos.show_season.save(ShowSeason(torrent_id=other.id, season=2, season_to=2, show_id=300))
        _save_local_info(repos, other, original_file_path="S2.mkv", symlink_path="/x/S2.mkv")

        interrupt_event = asyncio.Event()
        interrupt_event.set()

        svc.bittorrent.add_torrent = AsyncMock()
        asyncio.run(svc._phase_show(request, interrupt_event))
        svc.bittorrent.add_torrent.assert_not_called()

    def test_skips_seasons_without_torrent_file(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(
            fake_config, repos, imdb="tt7600001", torrent_id=7601, show_id=400,
        )
        other = _save_show_torrent(repos, imdb="tt7600001", torrent_id=7602)
        repos.show_season.save(ShowSeason(torrent_id=other.id, season=2, season_to=2, show_id=400))
        # Saved LocalFileInformation but no torrent_file_local_path
        _save_local_info(repos, other, torrent_file_local_path="", original_file_path="x", symlink_path="/x")

        svc.bittorrent.add_torrent = AsyncMock()
        asyncio.run(svc._phase_show(request))
        svc.bittorrent.add_torrent.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
#  Show download — orchestration
# ═════════════════════════════════════════════════════════════════════════════

class TestHandleShowDownload:
    def test_runs_all_3_phases_on_success(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos)

        svc._phase_episode = AsyncMock(return_value=True)
        svc._phase_season = AsyncMock(return_value=True)
        svc._phase_show = AsyncMock(return_value=None)

        asyncio.run(svc._handle_show_download(request))

        svc._phase_episode.assert_awaited_once()
        svc._phase_season.assert_awaited_once()
        svc._phase_show.assert_awaited_once()

    def test_stops_after_phase1_if_interrupted(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos)

        svc._phase_episode = AsyncMock(return_value=False)
        svc._phase_season = AsyncMock(return_value=True)
        svc._phase_show = AsyncMock(return_value=None)

        asyncio.run(svc._handle_show_download(request))

        svc._phase_episode.assert_awaited_once()
        svc._phase_season.assert_not_called()
        svc._phase_show.assert_not_called()

    def test_stops_after_phase2_if_interrupted(self, fake_config, repos):
        svc = _make_service(fake_config)
        request = _make_show_request(fake_config, repos)

        svc._phase_episode = AsyncMock(return_value=True)
        svc._phase_season = AsyncMock(return_value=False)
        svc._phase_show = AsyncMock(return_value=None)

        asyncio.run(svc._handle_show_download(request))

        svc._phase_episode.assert_awaited_once()
        svc._phase_season.assert_awaited_once()
        svc._phase_show.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
#  Orchestrator dispatch
# ═════════════════════════════════════════════════════════════════════════════

class TestOrchestratorDispatch:
    def test_dispatches_movie_to_movie_handler(self, fake_config, repos):
        svc = _make_service(fake_config)
        torrent = _save_movie_torrent(repos, imdb="tt9100001", torrent_id=9101)
        info = _save_local_info(repos, torrent)
        request = MediaDownloadRequest(
            imdb_id="tt9100001", played_path="/x", jellyfin_item_id="x",
            torrent=torrent, local_info=info, episode_file_index=0,
        )

        svc._handle_movie_download = AsyncMock()
        svc._handle_show_download = AsyncMock()

        async def _drive():
            await svc._media_download_queue.put(request)
            task = asyncio.create_task(svc._download_orchestrator())
            # Give the orchestrator a chance to pick up the item
            for _ in range(20):
                await asyncio.sleep(0)
                if svc._handle_movie_download.await_count == 1:
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_drive())

        svc._handle_movie_download.assert_awaited_once()
        svc._handle_show_download.assert_not_called()

    def test_dispatches_show_to_show_handler(self, fake_config, repos):
        svc = _make_service(fake_config)
        torrent = _save_show_torrent(repos, imdb="tt9200001", torrent_id=9201)
        info = _save_local_info(repos, torrent)
        request = MediaDownloadRequest(
            imdb_id="tt9200001", played_path="/x", jellyfin_item_id="x",
            torrent=torrent, local_info=info, episode_file_index=0,
        )

        svc._handle_movie_download = AsyncMock()
        svc._handle_show_download = AsyncMock()

        async def _drive():
            await svc._media_download_queue.put(request)
            task = asyncio.create_task(svc._download_orchestrator())
            for _ in range(20):
                await asyncio.sleep(0)
                if svc._handle_show_download.await_count == 1:
                    break
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_drive())

        svc._handle_show_download.assert_awaited_once()
        svc._handle_movie_download.assert_not_called()

    def test_orchestrator_clears_inflight_key_after_exception(self, fake_config, repos):
        svc = _make_service(fake_config)
        torrent = _save_movie_torrent(repos, imdb="tt9300001", torrent_id=9301)
        info = _save_local_info(repos, torrent)
        request = MediaDownloadRequest(
            imdb_id="tt9300001", played_path="/x", jellyfin_item_id="x",
            torrent=torrent, local_info=info, episode_file_index=0,
        )

        svc._handle_movie_download = AsyncMock(side_effect=RuntimeError("boom"))
        svc._inflight_keys.add(("x", 0))

        async def _drive():
            await svc._media_download_queue.put(request)
            task = asyncio.create_task(svc._download_orchestrator())
            for _ in range(20):
                await asyncio.sleep(0)
                if svc._handle_movie_download.await_count == 1:
                    break
            await asyncio.sleep(0)  # let finally run
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            for active_task in list(svc._active_download_tasks):
                await active_task

        asyncio.run(_drive())
        assert ("x", 0) not in svc._inflight_keys
