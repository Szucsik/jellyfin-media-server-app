"""Tests for the FastAPI endpoints in src/parsing_api.py."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

import parsing_api


class TestFixLooseLinksEndpoint:
    def test_endpoint_repairs_broken_symlinks_and_returns_summary(self, fake_config, monkeypatch):
        movies = Path(fake_config.symlink_movies_directory)
        broken = movies / "Some Movie [imdbid-tt0000001]" / "movie.mp4"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.symlink_to(movies / "missing.mp4")

        monkeypatch.setattr(parsing_api, "config", fake_config)
        client = TestClient(parsing_api.app)

        response = client.post("/fix-loose-links")

        assert response.status_code == 200
        payload = response.json()
        assert payload["broken_links_detected"] == 1
        assert payload["repaired"] == 1
        assert payload["failed"] == 0
        assert payload["directories_scanned"]
        assert broken.is_symlink()
        assert Path(os.readlink(broken)) == Path(fake_config.placeholder_starter_path)

    def test_endpoint_reports_invalid_placeholder_without_repairing(self, fake_config, monkeypatch):
        movies = Path(fake_config.symlink_movies_directory)
        broken = movies / "broken.mp4"
        broken.symlink_to(movies / "missing.mp4")
        fake_config.placeholder_starter_path = str(movies / "no-placeholder.mp4")

        monkeypatch.setattr(parsing_api, "config", fake_config)
        client = TestClient(parsing_api.app)

        response = client.post("/fix-loose-links")

        assert response.status_code == 200
        payload = response.json()
        assert payload["repaired"] == 0
        assert payload["errors"]
        assert broken.is_symlink() and not broken.exists()
