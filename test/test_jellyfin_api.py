"""Tests for src/jellyfin_api/jellyfin_api.py."""
from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import requests

from jellyfin_api.jellyfin_api import JellyfinApi


@pytest.fixture(autouse=True)
def isolated_api_key(fake_config):
    fake_config.jellyfin_api_key = uuid4().hex


# ─────────────────────────────────────────────────────────────────────────────
#  Construction / validation
# ─────────────────────────────────────────────────────────────────────────────

class TestConstruction:
    def test_strips_trailing_slash_from_url(self, fake_config):
        fake_config.jellyfin_url = "http://jellyfin.local:8096/"
        api = JellyfinApi(fake_config)
        assert api.server_url == "http://jellyfin.local:8096"

    def test_missing_api_key_raises(self, fake_config):
        fake_config.jellyfin_api_key = ""
        with pytest.raises(ValueError, match="JELLYFIN_API_KEY"):
            JellyfinApi(fake_config)

    def test_missing_user_id_raises(self, fake_config):
        fake_config.jellyfin_user_id = ""
        with pytest.raises(ValueError, match="JELLYFIN_USER_ID"):
            JellyfinApi(fake_config)

    def test_headers_contain_token(self, fake_config):
        api = JellyfinApi(fake_config)
        headers = api._headers()
        assert headers["Authorization"] == f'MediaBrowser Token="{fake_config.jellyfin_api_key}"'
        assert not any(name.startswith("X-Emby") or name.startswith("X-MediaBrowser") for name in headers)
        assert headers["Accept"] == "application/json"

    def test_api_key_is_loaded_from_environment(self, fake_config, monkeypatch):
        monkeypatch.setenv("JELLYFIN_API_KEY", fake_config.jellyfin_api_key)
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "src" / "config.py"))
        config = namespace["Configuration"]()
        api = JellyfinApi(config)
        assert api.api_key == fake_config.jellyfin_api_key
        assert api._headers()["Authorization"] == f'MediaBrowser Token="{fake_config.jellyfin_api_key}"'


# ─────────────────────────────────────────────────────────────────────────────
#  fetch_items
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchItems:
    def test_system_info_then_sessions_use_current_authentication(self, fake_config):
        api = JellyfinApi(fake_config)
        info_response = requests.Response()
        info_response.status_code = 200
        info_response._content = b'{}'
        sessions_response = requests.Response()
        sessions_response.status_code = 200
        sessions_response._content = b'[]'

        with patch("requests.sessions.Session.send", side_effect=[info_response, sessions_response]) as mock_send:
            info = requests.get(f"{api.server_url}/System/Info", headers=api._headers(), timeout=10)
            info.raise_for_status()
            assert api.fetch_items() == []

        assert [call.args[0].url for call in mock_send.call_args_list] == [
            f"{api.server_url}/System/Info",
            f"{api.server_url}/Sessions",
        ]
        for call in mock_send.call_args_list:
            headers = call.args[0].headers
            assert headers["Authorization"] == f'MediaBrowser Token="{fake_config.jellyfin_api_key}"'
            assert not any(name.startswith("X-Emby") or name.startswith("X-MediaBrowser") for name in headers)

    def test_returns_parsed_json_on_success(self, fake_config):
        api = JellyfinApi(fake_config)
        resp = MagicMock()
        resp.json.return_value = [{"Id": "1"}, {"Id": "2"}]
        resp.raise_for_status.return_value = None

        with patch("jellyfin_api.jellyfin_api.requests.get", return_value=resp) as mock_get:
            result = api.fetch_items()

        assert result == [{"Id": "1"}, {"Id": "2"}]
        mock_get.assert_called_once()
        url = mock_get.call_args.args[0]
        assert url.endswith("/Sessions")
        assert mock_get.call_args.kwargs["headers"] == api._headers()
        prepared = requests.Request("GET", url, headers=mock_get.call_args.kwargs["headers"]).prepare()
        assert prepared.headers["Authorization"] == f'MediaBrowser Token="{fake_config.jellyfin_api_key}"'
        assert "api_key" not in prepared.url

    def test_returns_empty_list_on_request_exception(self, fake_config):
        api = JellyfinApi(fake_config)
        with patch(
            "jellyfin_api.jellyfin_api.requests.get",
            side_effect=requests.RequestException("boom"),
        ):
            assert api.fetch_items() == []

    def test_returns_empty_list_on_http_error(self, fake_config):
        api = JellyfinApi(fake_config)
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("jellyfin_api.jellyfin_api.requests.get", return_value=resp):
            assert api.fetch_items() == []


# ─────────────────────────────────────────────────────────────────────────────
#  refresh_item
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshItem:
    def test_posts_with_correct_url_and_params(self, fake_config):
        api = JellyfinApi(fake_config)
        resp = MagicMock()
        resp.raise_for_status.return_value = None

        with patch("jellyfin_api.jellyfin_api.requests.post", return_value=resp) as mock_post:
            api.refresh_item("abc123")

        assert mock_post.called
        called_url = mock_post.call_args.args[0]
        assert called_url.endswith("/Items/abc123/Refresh")
        assert mock_post.call_args.kwargs["headers"] == api._headers()
        params = mock_post.call_args.kwargs["params"]
        assert params["metadataRefreshMode"] == "FullRefresh"
        assert params["replaceAllMetadata"] == "false"

    def test_swallows_request_exception(self, fake_config):
        api = JellyfinApi(fake_config)
        with patch(
            "jellyfin_api.jellyfin_api.requests.post",
            side_effect=requests.RequestException("boom"),
        ):
            # Should not raise
            api.refresh_item("abc123")


class TestLibraryAuditor:
    @pytest.mark.parametrize("path", ["/System/Info", "/Sessions", "/Items", "/Users/user-1/Items", "/Shows/series-1/Seasons"])
    def test_get_uses_current_authentication(self, fake_config, path):
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "jellyfin-tests" / "anomalies.py"))
        response = MagicMock()
        response.json.return_value = {"Items": []}

        with patch("requests.get", return_value=response) as mock_get:
            result = namespace["jf_get"](fake_config.jellyfin_url, fake_config.jellyfin_api_key, path)

        assert result == {"Items": []}
        assert mock_get.call_args.args[0] == f"{fake_config.jellyfin_url}{path}"
        assert mock_get.call_args.kwargs["headers"] == {
            "Authorization": f'MediaBrowser Token="{fake_config.jellyfin_api_key}"',
        }
        assert "api_key" not in mock_get.call_args.kwargs["params"]
        response.raise_for_status.assert_called_once()
