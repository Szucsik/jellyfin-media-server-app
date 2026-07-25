"""Tests for src/jellyfin_api/bittorrentapi.py."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jellyfin_api.bittorrentapi import (
    BittorrentAPI,
    SPEED_20_MBPS,
    SPEED_UNLIMITED,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _torrent_file(name: str, index: int, size: int = 1000, progress: float = 0.0, priority: int = 1):
    return SimpleNamespace(name=name, index=index, size=size, progress=progress, priority=priority)


def _torrent_info(
    state: str = "downloading",
    progress: float = 0.0,
    dlspeed: int = 1_000_000,
    eta: int = 600,
    save_path: str = "/downloads/foo",
    num_seeds: int = 5,
    num_leechs: int = 1,
):
    ns = SimpleNamespace(
        state=state,
        progress=progress,
        dlspeed=dlspeed,
        save_path=save_path,
        num_seeds=num_seeds,
        num_leechs=num_leechs,
    )
    ns.get = lambda key, default=None: getattr(ns, key, default)
    return ns


def _make_api(fake_config) -> BittorrentAPI:
    return BittorrentAPI(fake_config)


# ─────────────────────────────────────────────────────────────────────────────
#  Connection
# ─────────────────────────────────────────────────────────────────────────────

class TestConnect:
    def test_connect_creates_and_caches_client(self, fake_config):
        api = _make_api(fake_config)

        fake_client = MagicMock()
        fake_client.app.version = "v4.5.0"
        fake_client.auth_log_in.return_value = None

        with patch(
            "jellyfin_api.bittorrentapi.qbittorrentapi.Client",
            return_value=fake_client,
        ) as cls:
            client1 = asyncio.run(api.connect())
            client2 = asyncio.run(api.connect())

        assert client1 is fake_client
        assert client2 is fake_client
        # Cached → Client() only instantiated once
        cls.assert_called_once()
        fake_client.auth_log_in.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
#  add_torrent
# ─────────────────────────────────────────────────────────────────────────────

class TestAddTorrent:
    def test_adds_when_not_present_and_returns_hash(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()

        # First call: empty (not present), then non-empty during metadata wait
        existing = []
        ready = [_torrent_info(state="downloading")]
        api._client.torrents_info.side_effect = [existing, ready]
        api._client.torrents_add.return_value = "Ok."

        with patch.object(BittorrentAPI, "get_torrent_hash", return_value="abc"):
            result = asyncio.run(api.add_torrent("/tmp/x.torrent"))

        assert result == "abc"
        api._client.torrents_add.assert_called_once()

    def test_does_not_readd_when_already_present(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()

        present = [_torrent_info(state="downloading")]
        api._client.torrents_info.side_effect = [present, present]

        with patch.object(BittorrentAPI, "get_torrent_hash", return_value="abc"):
            result = asyncio.run(api.add_torrent("/tmp/x.torrent"))

        assert result == "abc"
        api._client.torrents_add.assert_not_called()

    def test_waits_through_metaDL_state(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()

        # Not present, then metaDL twice, then downloading
        api._client.torrents_info.side_effect = [
            [],
            [_torrent_info(state="metaDL")],
            [_torrent_info(state="checkingResumeData")],
            [_torrent_info(state="downloading")],
        ]

        _real_sleep = asyncio.sleep
        with patch.object(BittorrentAPI, "get_torrent_hash", return_value="hh"), \
             patch("jellyfin_api.bittorrentapi.asyncio.sleep", new=lambda s: _real_sleep(0)):
            result = asyncio.run(api.add_torrent("/tmp/x.torrent"))

        assert result == "hh"
        # Three calls inside the wait loop
        assert api._client.torrents_info.call_count == 4


# ─────────────────────────────────────────────────────────────────────────────
#  Simple delegating methods
# ─────────────────────────────────────────────────────────────────────────────

class TestSimpleDelegators:
    def test_get_torrent_files_returns_dict_list(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_files.return_value = [
            _torrent_file("a.mkv", 0, size=100, progress=0.5, priority=1),
            _torrent_file("b.mkv", 1, size=200, progress=1.0, priority=7),
        ]
        out = asyncio.run(api.get_torrent_files("hash"))
        assert out == [
            {"name": "a.mkv", "index": 0, "size": 100, "progress": 0.5, "priority": 1},
            {"name": "b.mkv", "index": 1, "size": 200, "progress": 1.0, "priority": 7},
        ]

    def test_set_file_priorities_calls_client(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        asyncio.run(api.set_file_priorities("hash", [1, 2, 3], 7))
        api._client.torrents_file_priority.assert_called_once_with(
            torrent_hash="hash", file_ids=[1, 2, 3], priority=7,
        )

    def test_set_download_limit_unlimited(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        asyncio.run(api.set_download_limit("h", SPEED_UNLIMITED))
        api._client.torrents_set_download_limit.assert_called_once_with(
            limit=0, torrent_hashes="h",
        )

    def test_set_download_limit_throttled(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        asyncio.run(api.set_download_limit("h", SPEED_20_MBPS))
        api._client.torrents_set_download_limit.assert_called_once_with(
            limit=SPEED_20_MBPS, torrent_hashes="h",
        )

    def test_get_save_path_returns_path_when_found(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_info.return_value = [_torrent_info(save_path="/data/foo")]
        assert asyncio.run(api.get_save_path("h")) == "/data/foo"

    def test_get_save_path_returns_empty_when_missing(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_info.return_value = []
        assert asyncio.run(api.get_save_path("h")) == ""


# ─────────────────────────────────────────────────────────────────────────────
#  wait_for_files_complete
# ─────────────────────────────────────────────────────────────────────────────

class TestWaitForFilesComplete:
    def test_returns_true_when_files_already_complete(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_files.return_value = [
            _torrent_file("a.mkv", 0, progress=1.0),
            _torrent_file("b.mkv", 1, progress=0.5),
        ]
        # Should not poll torrents_info since target files (index 0) are complete
        api._client.torrents_info.return_value = [_torrent_info()]

        result = asyncio.run(api.wait_for_files_complete("h", [0]))
        assert result is True

    def test_returns_false_when_interrupted(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_files.return_value = [_torrent_file("a.mkv", 0, progress=0.0)]

        async def _run():
            event = asyncio.Event()
            event.set()
            return await api.wait_for_files_complete("h", [0], interrupt_event=event)

        assert asyncio.run(_run()) is False

    def test_eventually_completes_after_progress(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_files.side_effect = [
            [_torrent_file("a.mkv", 0, progress=0.3)],
            [_torrent_file("a.mkv", 0, progress=1.0)],
        ]
        api._client.torrents_info.return_value = [_torrent_info(eta=120)]

        _real_sleep = asyncio.sleep
        with patch("jellyfin_api.bittorrentapi.asyncio.sleep", new=lambda s: _real_sleep(0)):
            result = asyncio.run(api.wait_for_files_complete("h", [0]))
        assert result is True
        assert api._client.torrents_files.call_count == 2

    def test_does_not_complete_when_target_files_temporarily_missing(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_files.side_effect = [
            [_torrent_file("other.mkv", 1, progress=0.2)],
            [_torrent_file("a.mkv", 0, progress=1.0)],
        ]
        api._client.torrents_info.return_value = [_torrent_info(eta=-1, dlspeed=1_000_000)]

        _real_sleep = asyncio.sleep
        with patch("jellyfin_api.bittorrentapi.asyncio.sleep", new=lambda s: _real_sleep(0)):
            result = asyncio.run(api.wait_for_files_complete("h", [0]))

        assert result is True
        assert api._client.torrents_files.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
#  wait_for_torrent_complete
# ─────────────────────────────────────────────────────────────────────────────

class TestWaitForTorrentComplete:
    def test_returns_true_on_done_state(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_info.return_value = [_torrent_info(state="uploading", progress=1.0)]
        api._client.torrents_files.return_value = [_torrent_file("a.mkv", 0, progress=1.0, priority=1)]

        assert asyncio.run(api.wait_for_torrent_complete("h")) is True

    def test_returns_false_when_interrupted(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_info.return_value = [_torrent_info(state="downloading", progress=0.2)]

        async def _run():
            event = asyncio.Event()
            event.set()
            return await api.wait_for_torrent_complete("h", interrupt_event=event)

        assert asyncio.run(_run()) is False

    def test_loops_until_progress_complete(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_info.side_effect = [
            [_torrent_info(state="downloading", progress=0.3)],
            [_torrent_info(state="downloading", progress=1.0)],
        ]
        api._client.torrents_files.side_effect = [
            [_torrent_file("a.mkv", 0, progress=0.3, priority=1)],
            [_torrent_file("a.mkv", 0, progress=1.0, priority=1)],
        ]

        _real_sleep = asyncio.sleep
        with patch("jellyfin_api.bittorrentapi.asyncio.sleep", new=lambda s: _real_sleep(0)):
            assert asyncio.run(api.wait_for_torrent_complete("h")) is True

    def test_handles_no_torrent_info_then_completes(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_info.side_effect = [
            [],
            [_torrent_info(state="uploading", progress=1.0)],
        ]
        api._client.torrents_files.return_value = [_torrent_file("a.mkv", 0, progress=1.0, priority=1)]
        _real_sleep = asyncio.sleep
        with patch("jellyfin_api.bittorrentapi.asyncio.sleep", new=lambda s: _real_sleep(0)):
            assert asyncio.run(api.wait_for_torrent_complete("h")) is True

    def test_does_not_finish_when_done_state_but_enabled_files_incomplete(self, fake_config):
        api = _make_api(fake_config)
        api._client = MagicMock()
        api._client.torrents_info.side_effect = [
            [_torrent_info(state="uploading", progress=1.0)],
            [_torrent_info(state="uploading", progress=1.0)],
        ]
        api._client.torrents_files.side_effect = [
            [_torrent_file("a.mkv", 0, progress=0.5, priority=1)],
            [_torrent_file("a.mkv", 0, progress=1.0, priority=1)],
        ]

        _real_sleep = asyncio.sleep
        with patch("jellyfin_api.bittorrentapi.asyncio.sleep", new=lambda s: _real_sleep(0)):
            assert asyncio.run(api.wait_for_torrent_complete("h")) is True

        assert api._client.torrents_info.call_count == 2
        assert api._client.torrents_files.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
#  _update_eta_placeholders
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateEtaPlaceholders:
    def _make_symlink(self, tmp_path: Path, name: str, target: Path) -> Path:
        link = tmp_path / name
        link.symlink_to(target)
        return link

    def test_skips_when_eta_negative(self, fake_config, tmp_path):
        api = _make_api(fake_config)
        link = self._make_symlink(tmp_path, "ep.mp4", Path(fake_config.placeholder_starter_path))
        api._update_eta_placeholders(-1, [str(link)])
        assert link.resolve() == Path(fake_config.placeholder_starter_path).resolve()

    def test_skips_when_eta_is_unknown_sentinel(self, fake_config, tmp_path):
        api = _make_api(fake_config)
        link = self._make_symlink(tmp_path, "ep.mp4", Path(fake_config.placeholder_starter_path))
        api._update_eta_placeholders(8640000, [str(link)])
        assert link.resolve() == Path(fake_config.placeholder_starter_path).resolve()

    @pytest.mark.parametrize(
        "seconds,expected_attr",
        [
            (3700, "placeholder_one_hr_left_path"),       # > 60 min
            (3600, "placeholder_one_hr_left_path"),       # exactly 60 min → >=60 branch
            (2400, "placeholder_half_hr_left_path"),      # 40 min
            (1500, "placeholder_less_then_twenty_min_left_path"),   # 25 min
            (900, "placeholder_less_then_ten_min_left_path"),       # 15 min
            (400, "placeholder_less_then_five_min_left_path"),      # 6.66 min
            (60, "placeholder_less_then_a_few_min_left_path"),      # 1 min
        ],
    )
    def test_eta_to_placeholder_mapping(self, fake_config, tmp_path, seconds, expected_attr):
        api = _make_api(fake_config)
        link = self._make_symlink(tmp_path, "ep.mp4", Path(fake_config.placeholder_starter_path))

        api._update_eta_placeholders(seconds, [str(link)])

        expected = Path(getattr(fake_config, expected_attr)).resolve()
        assert link.is_symlink()
        assert link.resolve() == expected

    def test_updates_multiple_symlinks(self, fake_config, tmp_path):
        api = _make_api(fake_config)
        l1 = self._make_symlink(tmp_path, "ep1.mp4", Path(fake_config.placeholder_starter_path))
        l2 = self._make_symlink(tmp_path, "ep2.mp4", Path(fake_config.placeholder_starter_path))

        api._update_eta_placeholders(60, [str(l1), str(l2)])

        target = Path(fake_config.placeholder_less_then_a_few_min_left_path).resolve()
        assert l1.resolve() == target
        assert l2.resolve() == target


# ─────────────────────────────────────────────────────────────────────────────
#  torrent_task
# ─────────────────────────────────────────────────────────────────────────────

class TestTorrentTask:
    def test_completes_and_returns_save_path(self, fake_config):
        api = _make_api(fake_config)

        async def _fake_add(*a, **kw): return "hashy"
        async def _fake_wait(*a, **kw): return True
        async def _fake_save(*a, **kw): return "/data/movie"

        with patch.object(api, "add_torrent", side_effect=_fake_add), \
             patch.object(api, "wait_for_torrent_complete", side_effect=_fake_wait), \
             patch.object(api, "get_save_path", side_effect=_fake_save):
            result = asyncio.run(api.torrent_task("/tmp/x.torrent", []))
        assert result == "/data/movie"

    def test_returns_empty_when_not_completed(self, fake_config):
        api = _make_api(fake_config)

        async def _fake_add(*a, **kw): return "hashy"
        async def _fake_wait(*a, **kw): return False

        with patch.object(api, "add_torrent", side_effect=_fake_add), \
             patch.object(api, "wait_for_torrent_complete", side_effect=_fake_wait):
            result = asyncio.run(api.torrent_task("/tmp/x.torrent", []))
        assert result == ""

    def test_forwards_placeholder_callback(self, fake_config):
        api = _make_api(fake_config)

        async def _fake_add(*a, **kw): return "hashy"
        wait_mock = MagicMock()

        async def _fake_wait(*a, **kw):
            wait_mock(*a, **kw)
            return False

        with patch.object(api, "add_torrent", side_effect=_fake_add), \
             patch.object(api, "wait_for_torrent_complete", side_effect=_fake_wait):
            asyncio.run(api.torrent_task("/tmp/x.torrent", [], on_placeholder_updated=lambda: None))

        assert callable(wait_mock.call_args.kwargs["on_placeholder_updated"])
