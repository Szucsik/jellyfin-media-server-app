"""Smoke tests for the SQLModel table definitions."""
from models.local_file_information import LocalFileInformation
from models.movie import Movie
from models.show import Show
from models.show_season import ShowSeason
from models.torrent import Quality, Torrent


def test_torrent_defaults():
    t = Torrent()
    assert t.title == ""
    assert t.imdb_link == ""
    assert t.is_show is False
    assert t.quality is Quality.UNASSIGNED
    assert t.torrent_id == -1
    assert t.seeders_number == -1
    assert t.leechers_number == -1


def test_quality_enum_values():
    assert Quality.SD.value == "720"
    assert Quality.HD.value == "1080"
    assert Quality.UHD.value == "2160"
    assert Quality.UNASSIGNED.value == "UNASSIGNED"


def test_movie_defaults():
    m = Movie(torrent_id=42)
    assert m.torrent_id == 42
    assert m.id is None


def test_show_requires_imdb_link():
    s = Show(imdb_link="https://www.imdb.com/title/tt0000001/")
    assert s.imdb_link.endswith("tt0000001/")


def test_show_season_defaults():
    ss = ShowSeason(torrent_id=1)
    assert ss.season == -1
    assert ss.season_to == -1
    assert ss.show_id == -1


def test_local_file_information_defaults():
    lfi = LocalFileInformation(torrent_id=1)
    assert lfi.torrent_file_local_path == ""
    assert lfi.main_media_files_local_path == ""
    assert lfi.original_file_path == ""
    assert lfi.symlink_path == ""
