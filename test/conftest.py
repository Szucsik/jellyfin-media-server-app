"""
Shared pytest fixtures and environment setup.

This file is loaded before any test module is collected, so it is the right
place to:

  * inject the env-vars that ``src/config.py`` reads at class-body load time
    (otherwise the import of ``config`` raises ``ValueError``);
  * make sure ``src/`` is importable as a top-level package root;
  * provide reusable fixtures (in-memory DB engine, fake Configuration,
    factories for Torrent / Movie / Show / ShowSeason / LocalFileInformation).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ── 1.  Make `src/` importable BEFORE we import anything from it ──────────────
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

# ── 2.  Set required env vars BEFORE the first `import config` happens ───────
_PLACEHOLDER_DIR = tempfile.mkdtemp(prefix="jf-placeholders-")
_TORRENTS_DIR = tempfile.mkdtemp(prefix="jf-torrents-")
_MOVIES_DIR = tempfile.mkdtemp(prefix="jf-movies-")
_SERIES_DIR = tempfile.mkdtemp(prefix="jf-series-")
_DOWNLOADED_DIR = tempfile.mkdtemp(prefix="jf-downloaded-")

# Touch placeholder files referenced as Configuration.placeholder_*_path
for fname in (
    "jellyfin-placeholder.mp4",
    "jellyfin-placeholder-1-hour-left.mp4",
    "jellyfin-placeholder-less-then-1-hour-left.mp4",
    "jellyfin-placeholder-half-hour-left.mp4",
    "jellyfin-placeholder-less-then-20-minutes-left.mp4",
    "jellyfin-placeholder-less-then-10-minutes-left.mp4",
    "jellyfin-placeholder-less-then-5-minutes-left.mp4",
    "jellyfin-placeholder-less-then-a-few-minutes-left.mp4",
):
    Path(_PLACEHOLDER_DIR, fname).touch()

os.environ.setdefault("NCORE_USERNAME", "tester")
os.environ.setdefault("NCORE_PASSWORD", "secret")
os.environ.setdefault("TORRENT_FILES_LOCATION", _TORRENTS_DIR)
os.environ.setdefault("TORRENT_FILES_TARGET_LOCATION", _TORRENTS_DIR)
os.environ.setdefault("VOLUME_SERIES_DIR", _SERIES_DIR)
os.environ.setdefault("VOLUME_MOVIE_DIR", _MOVIES_DIR)
os.environ.setdefault("VOLUME_PLACEHOLDER_TARGET_DIR", _PLACEHOLDER_DIR)
os.environ.setdefault("VOLUME_DOWNLOADED_DIR", _DOWNLOADED_DIR)
os.environ.setdefault("VOLUME_DOWNLOADED_TARGET_DIR", _DOWNLOADED_DIR)
os.environ.setdefault("JELLYFIN_URL", "http://jellyfin.local:8096")
os.environ.setdefault("JELLYFIN_USER_ID", "user-1")
os.environ.setdefault("JELLYFIN_API_KEY", "key-1")
os.environ.setdefault("TMDB_API_KEY", "tmdb-key")
os.environ.setdefault("QBITTORRENT_HOST", "127.0.0.1")
os.environ.setdefault("QBITTORRENT_PORT", "8080")
os.environ.setdefault("QBITTORRENT_USERNAME", "admin")
os.environ.setdefault("QBITTORRENT_PASSWORD", "adminadmin")

# ── 3.  Now safe to import application modules ───────────────────────────────
import pytest
from sqlmodel import SQLModel

from database.db import (
    LocalFilesRepository,
    MovieRepository,
    ShowRepository,
    ShowSeasonsRepository,
    TorrentRepository,
    _create_engine,
)
from models.local_file_information import LocalFileInformation
from models.movie import Movie
from models.show import Show
from models.show_season import ShowSeason
from models.torrent import Quality, Torrent


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    """Fresh in-memory SQLite engine with all tables created."""
    eng = _create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def repos(engine):
    """Bundle of repositories all pointing at the same in-memory engine."""
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


class FakeConfig:
    """A minimal Configuration stand-in that only carries the attributes the
    code under test actually touches."""

    def __init__(self, repos, *, tmp_path: Path | None = None) -> None:
        self.torrent_repository = repos.torrent
        self.movie_repository = repos.movie
        self.show_repository = repos.show
        self.show_season_repository = repos.show_season
        self.local_files_repository = repos.local_files

        self.username = "tester"
        self.password = "secret"
        self.tmdb_api_key = "tmdb-key"

        self.jellyfin_url = os.environ["JELLYFIN_URL"]
        self.jellyfin_api_key = os.environ["JELLYFIN_API_KEY"]
        self.jellyfin_user_id = os.environ["JELLYFIN_USER_ID"]

        self.qbittorrent_host = os.environ["QBITTORRENT_HOST"]
        self.qbittorrent_port = os.environ["QBITTORRENT_PORT"]
        self.qbittorrent_username = os.environ["QBITTORRENT_USERNAME"]
        self.qbittorrent_password = os.environ["QBITTORRENT_PASSWORD"]

        base = tmp_path or Path(tempfile.mkdtemp(prefix="jf-fake-"))
        (base / "movies").mkdir(exist_ok=True)
        (base / "series").mkdir(exist_ok=True)
        (base / "downloaded").mkdir(exist_ok=True)
        (base / "torrents").mkdir(exist_ok=True)
        ph = base / "placeholders"
        ph.mkdir(exist_ok=True)
        for fname in (
            "jellyfin-placeholder.mp4",
            "jellyfin-placeholder-1-hour-left.mp4",
            "jellyfin-placeholder-less-then-1-hour-left.mp4",
            "jellyfin-placeholder-half-hour-left.mp4",
            "jellyfin-placeholder-less-then-20-minutes-left.mp4",
            "jellyfin-placeholder-less-then-10-minutes-left.mp4",
            "jellyfin-placeholder-less-then-5-minutes-left.mp4",
            "jellyfin-placeholder-less-then-a-few-minutes-left.mp4",
        ):
            (ph / fname).touch()

        self.symlink_movies_directory = str(base / "movies")
        self.symlink_series_directory = str(base / "series")
        self.downloaded_directory = str(base / "downloaded")
        self.downloaded_target_directory = str(base / "downloaded")
        self.torrent_files_location = str(base / "torrents")
        self.torrent_files_target_location = str(base / "torrents")
        self.placeholders_directory = str(ph)

        self.placeholder_starter_path = str(ph / "jellyfin-placeholder.mp4")
        self.placeholder_one_hr_left_path = str(ph / "jellyfin-placeholder-1-hour-left.mp4")
        self.placeholder_less_then_one_hr_left_path = str(ph / "jellyfin-placeholder-less-then-1-hour-left.mp4")
        self.placeholder_half_hr_left_path = str(ph / "jellyfin-placeholder-half-hour-left.mp4")
        self.placeholder_less_then_twenty_min_left_path = str(ph / "jellyfin-placeholder-less-then-20-minutes-left.mp4")
        self.placeholder_less_then_ten_min_left_path = str(ph / "jellyfin-placeholder-less-then-10-minutes-left.mp4")
        self.placeholder_less_then_five_min_left_path = str(ph / "jellyfin-placeholder-less-then-5-minutes-left.mp4")
        self.placeholder_less_then_a_few_min_left_path = str(ph / "jellyfin-placeholder-less-then-a-few-minutes-left.mp4")

        import logging
        self.logger = logging.getLogger("test")

    def get_logger(self, name: str):
        import logging
        return logging.getLogger(name)


@pytest.fixture
def fake_config(repos, tmp_path):
    return FakeConfig(repos, tmp_path=tmp_path)


# ── Convenience factories ────────────────────────────────────────────────────

@pytest.fixture
def make_torrent():
    counter = {"n": 1000}

    def _make(
        title: str = "Some.Title.S01.1080p",
        imdb_link: str = "https://www.imdb.com/title/tt0000001/",
        quality: Quality = Quality.HD,
        is_show: bool = True,
        torrent_id: int | None = None,
        download_link: str = "",
        category: str = "HD",
        seeders_number: int = 0,
        leechers_number: int = 0,
        detail_link: str = "",
    ) -> Torrent:
        counter["n"] += 1
        return Torrent(
            title=title,
            imdb_link=imdb_link,
            quality=quality,
            is_show=is_show,
            torrent_id=torrent_id if torrent_id is not None else counter["n"],
            download_link=download_link,
            category=category,
            seeders_number=seeders_number,
            leechers_number=leechers_number,
            detail_link=detail_link,
        )

    return _make
