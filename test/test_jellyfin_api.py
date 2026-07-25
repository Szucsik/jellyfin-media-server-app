"""Tests for src/jellyfin_api/jellyfin_api.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from jellyfin_api.jellyfin_api import JellyfinApi


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
        assert fake_config.jellyfin_api_key in headers["X-Emby-Authorization"]
        assert headers["Accept"] == "application/json"


# ─────────────────────────────────────────────────────────────────────────────
#  fetch_items
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchItems:
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
