from ncore_scraper.models import Quality, Torrent
from ncore_scraper.scraper import Scraper
import pytest


@pytest.fixture(scope="module")
def scraper():
    return Scraper(username="john", password="doe", for_test=True)

def test_data_distillation(scraper):
    torrents: list[Torrent] = [
        Torrent(imdb_link="a",quality=Quality.HD),
        Torrent(imdb_link="a",quality=Quality.SD),
        Torrent(imdb_link="a",quality=Quality.HD),
        Torrent(imdb_link="c",quality=Quality.UHD),
        Torrent(imdb_link="b",quality=Quality.HD),
        Torrent(imdb_link="a",quality=Quality.UNASSIGNED),
        Torrent(imdb_link="a",quality=Quality.HD),
        Torrent(imdb_link="b",quality=Quality.SD),
        Torrent(imdb_link="a",quality=Quality.HD),
        Torrent(imdb_link="q",quality=Quality.UNASSIGNED),
        Torrent(imdb_link="f",quality=Quality.UHD),
        Torrent(imdb_link="q",quality=Quality.SD),
        Torrent(imdb_link="b",quality=Quality.UHD),
    ]

    expected_torrents: list[Torrent] = [
        Torrent(imdb_link="a",quality=Quality.HD),
        Torrent(imdb_link="c",quality=Quality.UHD),
        Torrent(imdb_link="b",quality=Quality.UHD),
        Torrent(imdb_link="f",quality=Quality.UHD),
        Torrent(imdb_link="q",quality=Quality.SD),
    ]

    result_torrents = scraper._distillation_torrent_data(torrents)

    for result in result_torrents:
        if result in expected_torrents:
            expected_torrents.pop(expected_torrents.index(result))

    assert len(expected_torrents) == 0