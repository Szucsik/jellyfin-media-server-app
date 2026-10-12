"""Tests for src/subtitle_sync/service.py."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from jellyfin_api.jellyfin_api import JellyfinApi
from models.local_file_information import LocalFileInformation
from models.torrent import Torrent
from subtitle_sync.service import SubtitleSyncService
from sync import MediaDownloadRequest, TorrentSyncService


class StubJellyfin:
    """Minimal JellyfinApi stand-in recording the subtitle calls made."""

    item_has_subtitle_language = staticmethod(JellyfinApi.item_has_subtitle_language)

    def __init__(self, item=None, candidates=None, download_ok=True):
        self.item = item
        self.candidates = candidates or []
        self.download_ok = download_ok
        self.searches: list[str] = []
        self.downloads: list[tuple[str, str]] = []

    def get_item(self, item_id: str):
        return self.item

    def search_remote_subtitles(self, item_id: str, language: str) -> list[dict]:
        self.searches.append(item_id)
        return self.candidates

    def download_remote_subtitle(self, item_id: str, subtitle_id: str) -> bool:
        self.downloads.append((item_id, subtitle_id))
        return self.download_ok


def _service(fake_config, **kwargs) -> tuple[SubtitleSyncService, StubJellyfin]:
    stub = StubJellyfin(**kwargs)
    return SubtitleSyncService(fake_config, jellyfin=stub), stub


def _item(streams=None) -> dict:
    return {"Id": "jf-1", "MediaStreams": streams or []}


def test_downloads_first_candidate_when_no_hungarian_subtitle(fake_config):
    svc, stub = _service(
        fake_config,
        item=_item([{"Type": "Audio", "Language": "eng"}]),
        candidates=[{"Id": "sub-1"}],
    )

    assert svc.download_for_item("jf-1") == "downloaded"
    assert stub.searches == ["jf-1"]
    assert stub.downloads == [("jf-1", "sub-1")]


def test_skips_when_hungarian_subtitle_present(fake_config):
    svc, stub = _service(
        fake_config,
        item=_item([{"Type": "Subtitle", "Language": "hu"}]),
        candidates=[{"Id": "sub-1"}],
    )

    assert svc.download_for_item("jf-1") == "already_present"
    assert stub.searches == []
    assert stub.downloads == []


def test_returns_not_found_when_no_candidate(fake_config):
    svc, stub = _service(fake_config, item=_item(), candidates=[])

    assert svc.download_for_item("jf-1") == "not_found"
    assert stub.downloads == []


def test_returns_failed_when_download_fails(fake_config):
    svc, _ = _service(fake_config, item=_item(), candidates=[{"Id": "sub-1"}], download_ok=False)

    assert svc.download_for_item("jf-1") == "failed"


def test_returns_failed_when_item_cannot_be_fetched(fake_config):
    svc, stub = _service(fake_config, item=None)

    assert svc.download_for_item("jf-1") == "failed"
    assert stub.searches == []


def test_returns_failed_for_empty_item_id(fake_config):
    svc, stub = _service(fake_config, item=_item())

    assert svc.download_for_item("") == "failed"
    assert stub.searches == []


class TestItemHasSubtitleLanguage:
    def test_detects_matching_subtitle_stream(self):
        item = {"MediaStreams": [
            {"Type": "Subtitle", "Language": "hu"},
            {"Type": "Audio", "Language": "eng"},
        ]}
        assert JellyfinApi.item_has_subtitle_language(item, "hu") is True

    def test_ignores_non_subtitle_streams(self):
        item = {"MediaStreams": [{"Type": "Audio", "Language": "hu"}]}
        assert JellyfinApi.item_has_subtitle_language(item, "hu") is False

    def test_handles_missing_media_streams(self):
        assert JellyfinApi.item_has_subtitle_language({}, "hu") is False


# ─────────────────────────────────────────────────────────────────────────────
#  Sync service integration
# ─────────────────────────────────────────────────────────────────────────────

def _download_request(language: str) -> MediaDownloadRequest:
    return MediaDownloadRequest(
        imdb_id="tt1",
        played_path="/media/m.mkv",
        jellyfin_item_id="jf-1",
        torrent=Torrent(title="T", language=language),
        local_info=LocalFileInformation(),
        episode_file_index=0,
    )


def test_sync_fetches_subtitles_for_non_hungarian_media(fake_config):
    svc = TorrentSyncService(fake_config)
    svc.subtitles = MagicMock()
    svc.subtitles.download_for_item.return_value = "downloaded"

    asyncio.run(svc._ensure_hungarian_subtitles(_download_request("ENG")))

    svc.subtitles.download_for_item.assert_called_once_with("jf-1")


def test_sync_skips_subtitles_for_hungarian_media(fake_config):
    svc = TorrentSyncService(fake_config)
    svc.subtitles = MagicMock()

    asyncio.run(svc._ensure_hungarian_subtitles(_download_request("HUN")))

    svc.subtitles.download_for_item.assert_not_called()
