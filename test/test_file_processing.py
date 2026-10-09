"""Tests for src/data_processing/file_processing.py."""
from __future__ import annotations

import os
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


class TestFixLooseLinks:
    def _assert_points_at_placeholder(self, link: Path, fake_config) -> None:
        assert link.is_symlink()
        assert Path(os.readlink(link)) == Path(fake_config.placeholder_starter_path)

    def test_repairs_broken_symlink_keeping_original_path(self, fake_config):
        fp = FileProcessing(config=fake_config)
        movies = Path(fake_config.symlink_movies_directory)
        broken = movies / "Some Movie [imdbid-tt0000001]" / "movie.mp4"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.symlink_to(movies / "does-not-exist.mp4")

        summary = fp.fix_loose_links()

        assert summary["broken_links_detected"] == 1
        assert summary["repaired"] == 1
        assert summary["failed"] == 0
        assert broken.name == "movie.mp4"
        assert broken.parent == movies / "Some Movie [imdbid-tt0000001]"
        self._assert_points_at_placeholder(broken, fake_config)
        assert broken.exists()

    def test_scans_nested_directories_and_special_characters(self, fake_config):
        fp = FileProcessing(config=fake_config)
        series = Path(fake_config.symlink_series_directory)
        nested = series / "Some Show [imdbid-tt0000002]" / "Season 1"
        nested.mkdir(parents=True, exist_ok=True)
        broken = nested / "episode 1 (pilot) & more.mp4"
        broken.symlink_to(nested / "missing.mp4")

        summary = fp.fix_loose_links()

        assert summary["repaired"] == 1
        self._assert_points_at_placeholder(broken, fake_config)

    def test_valid_symlink_is_left_unchanged(self, fake_config):
        fp = FileProcessing(config=fake_config)
        movies = Path(fake_config.symlink_movies_directory)
        real = movies / "real.mp4"
        real.touch()
        valid = movies / "valid.mp4"
        valid.symlink_to(real)

        summary = fp.fix_loose_links()

        assert summary["broken_links_detected"] == 0
        assert summary["repaired"] == 0
        assert Path(os.readlink(valid)) == real

    def test_regular_files_and_directories_are_untouched(self, fake_config):
        fp = FileProcessing(config=fake_config)
        movies = Path(fake_config.symlink_movies_directory)
        (movies / "subdir").mkdir()
        regular = movies / "regular.txt"
        regular.write_text("keep me")
        # A dangling regular path is NOT a symlink and must not be repaired.
        missing = movies / "missing.txt"

        summary = fp.fix_loose_links()

        assert summary["broken_links_detected"] == 0
        assert summary["repaired"] == 0
        assert regular.read_text() == "keep me"
        assert (movies / "subdir").is_dir()
        assert not missing.exists()

    def test_missing_target_directory_is_reported(self, fake_config):
        fp = FileProcessing(config=fake_config)
        missing_dir = Path(fake_config.symlink_movies_directory) / "nope"
        fake_config.symlink_movies_directory = str(missing_dir)

        summary = fp.fix_loose_links()

        assert str(missing_dir) in summary["missing_directories"]
        assert str(missing_dir) not in summary["directories_scanned"]
        assert summary["repaired"] == 0

    def test_invalid_placeholder_skips_repair(self, fake_config):
        fp = FileProcessing(config=fake_config)
        movies = Path(fake_config.symlink_movies_directory)
        broken = movies / "broken.mp4"
        broken.symlink_to(movies / "missing.mp4")
        fake_config.placeholder_starter_path = str(movies / "no-placeholder.mp4")

        summary = fp.fix_loose_links()

        assert summary["repaired"] == 0
        assert summary["broken_links_detected"] == 0
        assert summary["errors"]
        assert broken.is_symlink()
        assert not broken.exists()

    def test_repair_failure_is_recorded_and_scan_continues(self, fake_config, monkeypatch):
        fp = FileProcessing(config=fake_config)
        movies = Path(fake_config.symlink_movies_directory)
        series = Path(fake_config.symlink_series_directory)
        first = movies / "a.mp4"
        second = series / "b.mp4"
        first.symlink_to(movies / "missing-a.mp4")
        second.symlink_to(series / "missing-b.mp4")

        original_repair = fp._repair_symlink
        calls = {"n": 0}

        def flaky_repair(symlink_path: Path, target_path: Path) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("simulated repair failure")
            original_repair(symlink_path, target_path)

        monkeypatch.setattr(fp, "_repair_symlink", flaky_repair)

        summary = fp.fix_loose_links()

        assert summary["broken_links_detected"] == 2
        assert summary["repaired"] == 1
        assert summary["failed"] == 1
        assert summary["errors"]
        assert first.is_symlink() and not first.exists()
        self._assert_points_at_placeholder(second, fake_config)
