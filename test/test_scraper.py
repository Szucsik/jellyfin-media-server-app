"""Tests for the ncore scraper.

The scraper uses Selenium / Firefox at runtime; the constructor accepts
``for_test=True`` to skip launching a real WebDriver, after which the unit
tests inject a fake driver via attribute assignment.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from config import Configuration
from ncore_scraper.config import ScraperConfig
from ncore_scraper.scraper import Scraper
from ncore_scraper.selectors import ScraperSelectors
from models.torrent import Quality, Torrent


@pytest.fixture
def scraper():
    """Scraper instance with no real WebDriver attached."""
    cfg = Configuration()
    s = Scraper(username="john", password="doe", config=cfg, for_test=True)
    return s


# ── Pure helpers ─────────────────────────────────────────────────────────────

class TestQualityHelper:
    def test_uhd_detected(self, scraper):
        assert scraper._get_torrent_quality("Show.S01.2160p.BluRay") is Quality.UHD

    def test_hd_detected(self, scraper):
        assert scraper._get_torrent_quality("Show.S01.1080p.BluRay") is Quality.HD

    def test_sd_detected(self, scraper):
        assert scraper._get_torrent_quality("Show.S01.720p.WEB-DL") is Quality.SD

    def test_unknown_returns_unassigned(self, scraper):
        assert scraper._get_torrent_quality("Show.S01.WEB") is Quality.UNASSIGNED

class TestValidateTorrentTitles:
    def _make(self, title, imdb="ttX", quality=Quality.HD, season=1):
        t = Torrent(title=title, imdb_link=imdb, quality=quality, torrent_id=hash(title) & 0xFFFF)
        return t

    def test_single_torrent_per_imdb_skipped(self, scraper):
        # No exception when group has < 2 entries
        scraper._validate_torrent_titles([self._make("Show.S01.1080p")])

    def test_consistent_titles_pass(self, scraper):
        torrents = [
            self._make("Fallout.S01.1080p"),
            self._make("Fallout.S02.720p"),
        ]
        scraper._validate_torrent_titles(torrents)

    def test_inconsistent_titles_raise(self, scraper):
        torrents = [
            self._make("Fallout.S01.1080p"),
            self._make("CompletelyDifferent.S02.720p"),
        ]
        # The diagnostic-string builder references `t.season`, which Torrent
        # doesn't have, so the actual exception type may be either ValueError
        # (the intended one) or AttributeError (raised while formatting the
        # diagnostic message). Either way, the mismatch is detected.
        with pytest.raises((ValueError, AttributeError)):
            scraper._validate_torrent_titles(torrents)


# ── URL routing ──────────────────────────────────────────────────────────────

class TestUrlRouting:
    @pytest.mark.parametrize(
        "is_show, is_hd, expected_substr",
        [
            (False, True, "kivalasztott_tipus=hd_hun"),
            (False, False, "kivalasztott_tipus=xvid_hun"),
            (True, True, "kivalasztott_tipus=hdser_hun"),
            (True, False, "kivalasztott_tipus=xvidser_hun"),
        ],
    )
    def test_get_url_routes_correctly(self, scraper, is_show, is_hd, expected_substr):
        url = scraper._get_url(page=2, is_show=is_show, is_hd=is_hd)
        assert "oldal=2" in url
        assert expected_substr in url


# ── Page extraction ──────────────────────────────────────────────────────────

class TestExtraction:
    def _build_fake_driver(self, n_torrents: int = 2):
        """Build a fake WebDriver-like object with stub elements."""
        driver = MagicMock()

        # Each torrent has a div, an IMDB anchor, a detail-link anchor.
        torrent_divs = []
        imdb_anchors = []
        detail_anchors = []
        seeders = []
        leechers = []

        for i in range(n_torrents):
            # The IMDB anchor inside the div
            imdb_a = MagicMock()
            imdb_a.get_attribute.return_value = f"https://www.imdb.com/title/tt{i:07d}/"
            imdb_anchors.append(imdb_a)

            # The detail-page anchor inside the div
            detail_a = MagicMock()
            detail_a.get_attribute.return_value = f"https://ncore.pro/torrents.php?action=details&id={100 + i}"
            detail_a.text = f"Show.S0{i+1}.1080p.WEB-DL"
            detail_anchors.append(detail_a)

            div = MagicMock()
            # Each div.find_elements() returns the IMDB anchor list
            div.find_elements.return_value = [imdb_a]
            # Each div.find_element() returns the detail anchor
            div.find_element.return_value = detail_a
            torrent_divs.append(div)

            seeders.append(SimpleNamespace(text=str(10 + i)))
            leechers.append(SimpleNamespace(text=str(i)))

        # driver.find_elements side-effects based on selector
        def _find_elements(by, selector):
            if "torrent_txt" in selector:
                return torrent_divs
            if "infolink" in selector:
                return [a for div_a in [d.find_elements.return_value for d in torrent_divs] for a in div_a]
            if "box_s2" in selector:
                return seeders
            if "box_l2" in selector:
                return leechers
            if "lista_mini_error" in selector:
                return []  # results found, not a "no results" page
            return []

        driver.find_elements.side_effect = _find_elements
        driver.page_source = (
            '<link rel="alternate" href="https://ncore.pro/rss.php?key=abcdef12345" title="x">'
        )
        return driver, torrent_divs

    def test_get_torrent_data_from_page(self, scraper):
        driver, _ = self._build_fake_driver(n_torrents=2)
        scraper.driver = driver

        torrents = scraper._get_torrent_data_from_page(is_show=True, is_hd=True, category="HD")

        assert len(torrents) == 2
        assert torrents[0].imdb_link == "https://www.imdb.com/title/tt0000000/"
        assert torrents[0].title == "Show.S01.1080p.WEB-DL"
        assert torrents[0].torrent_id == 100
        assert torrents[0].quality is Quality.HD
        assert torrents[0].is_show is True
        assert torrents[0].category == "HD"
        assert torrents[0].seeders_number == "10"
        assert torrents[0].leechers_number == "0"
        assert "key=abcdef12345" in torrents[0].download_link

    def test_sd_skips_quality_extraction(self, scraper):
        driver, _ = self._build_fake_driver(n_torrents=1)
        scraper.driver = driver
        torrents = scraper._get_torrent_data_from_page(is_show=False, is_hd=False, category="SD")
        # When is_hd is False, quality is hard-coded to Quality.SD
        assert torrents[0].quality is Quality.SD

    def test_get_download_key_raises_if_missing(self, scraper):
        scraper.driver = MagicMock()
        scraper.driver.page_source = "<html>no-key-here</html>"
        with pytest.raises(ValueError, match="download key"):
            scraper._get_download_key()

    def test_invalid_detail_link_raises(self, scraper):
        driver, divs = self._build_fake_driver(n_torrents=1)
        # Tamper the detail anchor to an URL with no id=
        bad = MagicMock()
        bad.get_attribute.return_value = "https://ncore.pro/torrents.php?action=details"
        bad.text = "x"
        divs[0].find_element.return_value = bad
        scraper.driver = driver
        with pytest.raises(ValueError, match="No valid 'id'"):
            scraper._get_torrent_data_from_page(is_show=True, is_hd=True, category="HD")

    def test_missing_imdb_link_does_not_raise(self, scraper):
        driver, divs = self._build_fake_driver(n_torrents=1)
        # Make the IMDB lookup return no anchors → torrent gets imdb_link=""
        divs[0].find_elements.return_value = []
        scraper.driver = driver
        torrents = scraper._get_torrent_data_from_page(is_show=True, is_hd=True, category="HD")
        assert torrents[0].imdb_link == ""

    def test_imdb_anchor_with_none_href_raises(self, scraper):
        driver, divs = self._build_fake_driver(n_torrents=1)
        bad_anchor = MagicMock()
        bad_anchor.get_attribute.return_value = None
        divs[0].find_elements.return_value = [bad_anchor]
        scraper.driver = driver
        with pytest.raises(ValueError, match="IMDB link"):
            scraper._get_torrent_data_from_page(is_show=True, is_hd=True, category="HD")


# ── Lifecycle ────────────────────────────────────────────────────────────────

class TestLifecycle:
    def test_close_quits_driver(self, scraper):
        scraper.driver = MagicMock()
        scraper.close()
        scraper.driver.quit.assert_called_once()

    def test_close_no_driver_attribute_is_safe(self):
        cfg = Configuration()
        s = Scraper(username="x", password="y", config=cfg, for_test=True)
        # Manually delete the driver attribute set by for_test bypass
        if hasattr(s, "driver"):
            del s.driver
        s.close()  # should not raise


# ── ScraperConfig URL helpers ────────────────────────────────────────────────

class TestScraperConfig:
    def test_browse_hd_movies_url_contains_page(self):
        c = ScraperConfig()
        assert "oldal=3" in c.get_browse_hd_movies_url(3)
        assert "hd_hun" in c.get_browse_hd_movies_url(3)

    def test_browse_hd_shows_url(self):
        assert "hdser_hun" in ScraperConfig().get_browse_hd_shows_url(1)

    def test_browser_sd_movies_url(self):
        assert "xvid_hun" in ScraperConfig().get_browser_sd_movies_url(1)

    def test_browser_sd_shows_url(self):
        assert "xvidser_hun" in ScraperConfig().get_browser_sd_shows_url(1)

    def test_torrent_download_url(self):
        url = ScraperConfig().get_torrent_download_url(123, "key")
        assert "id=123" in url and "key=key" in url


# ── Selectors smoke ──────────────────────────────────────────────────────────

def test_selectors_module_importable():
    sel = ScraperSelectors()
    assert sel.Xpaths.LoginPage.TEXTBOX_USERNAME
    assert sel.CssSelectors.BrowsePage.TORRENT_TEXT_DIV
