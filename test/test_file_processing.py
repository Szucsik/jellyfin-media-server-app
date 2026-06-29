"""Tests for src/data_processing/file_processing.py."""
from __future__ import annotations

from pathlib import Path

from data_processing.file_processing import FileProcessing


class TestFileProcessingCleanup:
    def test_removes_only_top_level_season_directories(self, fake_config):
        fp = FileProcessing(config=fake_config)

        series_root = Path(fake_config.symlink_series_directory)
        keep_show = series_root / "Some Show [imdbid-tt1234567]"
        keep_show.mkdir(parents=True, exist_ok=True)
        (keep_show / "Season 1").mkdir(parents=True, exist_ok=True)

        stray_1 = series_root / "Season 1"
        stray_202301 = series_root / "Season 202301"
        stray_1.mkdir(parents=True, exist_ok=True)
        stray_202301.mkdir(parents=True, exist_ok=True)

        fp._cleanup_stray_top_level_season_dirs()

        assert keep_show.exists()
        assert (keep_show / "Season 1").exists()
        assert not stray_1.exists()
        assert not stray_202301.exists()
