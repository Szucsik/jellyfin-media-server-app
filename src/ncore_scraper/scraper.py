import random
import re
import time
import logging

from selenium import webdriver
from selenium.webdriver.common.by import By

from ncore_scraper.config import ScraperConfig
from models import Torrent, Quality
from ncore_scraper.selectors import ScraperSelectors


class Scraper:
    """Scraper agent for ncore.pro — handles login, browsing, and torrent data extraction."""

    KEY_PATTERN = re.compile(r'<link rel="alternate" href=".*?\/rss\.php\?key=(?P<key>[a-z0-9]+)" title=".*"')
    ID_PATTERN = re.compile(r"id=(\d+)")

    def __init__(self, username: str, password: str, for_test: bool = False) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.info("Scraper initialized")

        self.username = username
        self.password = password
        self.logged_in = False

        self.config = ScraperConfig()
        self.selectors = ScraperSelectors()
        if for_test is not True:
            self.driver = webdriver.Firefox(self.config.driver_options)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def login(self) -> None:
        """Log in to ncore.pro and land on the home page."""
        self.logger.info("Login started")
        self._open_login_page()
        self._submit_credentials()
        self._handle_post_login_redirections()
        self.logged_in = True

    def get_all_hd_movies(self, max_pages: int = 5) -> list[Torrent]:
        """
        Collect HD movie torrents across multiple browse pages.

        Iterates through paginated results, stopping either when no more
        results are found or when `max_pages` is reached.
        """
        self._open_browse_hd_movie_page()

        torrents: list[Torrent] = []
        for page in range(1, max_pages + 1):
            self.__navigate(self.config.get_browse_hd_pages_url(page))

            # Stop if the "no results" indicator is absent (i.e., results exist)
            if not self.driver.find_elements(By.XPATH, self.selectors.Xpaths.BrowsePage.TEXT_NOT_FOUND_LIST):
                break

            torrents.extend(self._get_torrent_data_from_page())

        torrents = self._process_torrent_data(torrents)
        torrents = self._distillation_torrent_data(torrents)
        return torrents

    # -------------------------------------------------------------------------
    # Navigation helpers
    # -------------------------------------------------------------------------

    def _open_login_page(self) -> None:
        """Navigate to the login page, retrying until all form elements are present."""
        self.__navigate(self.config.login_url)

        required = [
            self.selectors.Xpaths.LoginPage.TEXTBOX_USERNAME,
            self.selectors.Xpaths.LoginPage.TEXTBOX_PASSWORD,
            self.selectors.Xpaths.LoginPage.BUTTON_LOGIN,
        ]

        while not self._all_elements_present(required):
            self.logger.warning("Login elements not found, retrying...")
            self.driver.get(self.config.login_url)
            self.__sleep()

    def _open_browse_hd_movie_page(self) -> None:
        """Navigate to the HD movie browse page, retrying until all controls are present."""
        self.__navigate(self.config.browse_hd_url)

        required = [
            self.selectors.Xpaths.BrowsePage.BUTTON_SORT_BY_SEEDERS,
            self.selectors.Xpaths.BrowsePage.CHECKBOX_HDHUN_FILTER,
            self.selectors.Xpaths.BrowsePage.TEXTBOX_SEARCH_FIELD,
        ]

        while not self._all_elements_present(required):
            self.logger.warning("Browse page elements not found, retrying...")
            self.driver.get(self.config.browse_hd_url)
            self.__sleep()

    def _all_elements_present(self, xpaths: list[str]) -> bool:
        """Return True only if every XPath resolves to at least one element."""
        return all(self.driver.find_elements(By.XPATH, xpath) for xpath in xpaths)

    # -------------------------------------------------------------------------
    # Torrent data extraction
    # -------------------------------------------------------------------------

    def _get_torrent_data_from_page(self) -> list[Torrent]:
        """
        Extract raw torrent data (IMDB links, titles, detail links) from the current page.
        `page` is accepted for future use (e.g., logging) but not used directly.
        """
        torrents = self._generate_torrent_stubs()
        torrents = self._populate_imdb_links(torrents)
        torrents = self._populate_torrent_details(torrents)
        return torrents

    def _generate_torrent_stubs(self) -> list[Torrent]:
        """Create one blank Torrent stub per IMDB link found on the current page."""
        count = len(self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.IMDB_LINKS))
        return [Torrent() for _ in range(count)]

    def _populate_imdb_links(self, torrents: list[Torrent]) -> list[Torrent]:
        """Write the IMDB URL into each Torrent stub in list order."""
        links = self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.IMDB_LINKS)
        for torrent, link in zip(torrents, links):
            torrent.imdb_link = link.get_attribute("href")
        return torrents

    def _populate_torrent_details(self, torrents: list[Torrent]) -> list[Torrent]:
        """Write the detail page URL and display title into each Torrent stub."""
        links = self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.TORRENT_DETAIL_LINK)
        for torrent, link in zip(torrents, links):
            torrent.detail_link = link.get_attribute("href")
            torrent.title = link.text
        return torrents

    def _process_torrent_data(self, torrents: list[Torrent]) -> list[Torrent]:
        """
        Enrich each Torrent with its numeric ID, download key, quality tag,
        and fully formed download URL — all derived from page source and title text.
        """
        key = self._get_download_key()

        for torrent in torrents:
            match = self.ID_PATTERN.search(torrent.detail_link)
            if not match:
                raise ValueError(f"No valid 'id' parameter found in URL: {torrent.detail_link}")

            torrent.torrent_id = int(match.group(1))
            torrent.key = key
            torrent.quality = self._get_torrent_quality(torrent.title)
            torrent.download_link = self.config.get_torrent_download_url(torrent_id=torrent.torrent_id, key=key)

        return torrents

    def _distillation_torrent_data(self, torrents: list[Torrent]) -> list[Torrent]:
        """
        Deduplicate torrents that share the same IMDB link, keeping only
        the highest-quality version. Entries with UNASSIGNED quality are
        always discarded when a better-quality duplicate exists.
        """
        # Build a dict keyed by IMDB link, keeping the best-quality Torrent
        best: dict[str, Torrent] = {}

        for torrent in torrents:
            key = torrent.imdb_link
            existing = best.get(key)

            if existing is None:
                best[key] = torrent
                continue

            # Prefer the torrent with the numerically higher quality value
            if torrent.quality == Quality.UNASSIGNED:
                continue  # Never replace a known-quality entry with an unassigned one
            if existing.quality == Quality.UNASSIGNED or int(torrent.quality.value) > int(existing.quality.value):
                best[key] = torrent

        return list(best.values())

    # -------------------------------------------------------------------------
    # Utility / page-source helpers
    # -------------------------------------------------------------------------

    def _get_download_key(self) -> str:
        """
        Extract the per-session RSS/download key from the page source.
        Raises ValueError if the key cannot be found.
        """
        match = self.KEY_PATTERN.search(self.driver.page_source)
        if not match:
            raise ValueError("Could not extract the download key from page source.")
        return match.group("key")

    def _get_torrent_quality(self, title: str) -> Quality:
        """
        Map a torrent title to a Quality enum by checking for known quality
        strings (e.g. '1080p', '4K'). Returns Quality.UNASSIGNED if no match.
        """
        return next(
            (q for q in Quality if q != Quality.UNASSIGNED and q.value in title),
            Quality.UNASSIGNED,
        )

    # -------------------------------------------------------------------------
    # Low-level WebDriver wrappers
    # -------------------------------------------------------------------------

    def _submit_credentials(self) -> None:
        """Fill in the username/password fields and click the login button."""
        self.__write_to_textbox(self.username, self.selectors.Xpaths.LoginPage.TEXTBOX_USERNAME, "USERNAME")
        self.__write_to_textbox(self.password, self.selectors.Xpaths.LoginPage.TEXTBOX_PASSWORD, "PASSWORD")
        self.__click_button(self.selectors.Xpaths.LoginPage.BUTTON_LOGIN, "LOGIN_BUTTON")

    def _handle_post_login_redirections(self) -> None:
        """
        Handle the various pages that ncore.pro may redirect to after login:
        - Premium upsell page  → navigate back home
        - Still on login page  → credentials were rejected
        - Home page            → optionally dismiss the welcome pop-up
        """
        url = self.driver.current_url

        if url == self.config.premium_shop_url:
            self.logger.info("Redirected to premium shop — navigating home")
            self.__click_button(self.selectors.Xpaths.HomePage.BUTTON_HOME_PAGE_FROM_PREMIUM, "BACK_TO_HOME")

        elif url == self.config.login_url:
            self.logger.error("Login failed — still on the login page")

        elif url == self.config.home_url:
            welcome_btn = self.selectors.Xpaths.HomePage.BUTTON_WELLCOME_MESSAGE_CLOSE
            if self.driver.find_elements(By.XPATH, welcome_btn):
                self.logger.info("Dismissing welcome message")
                self.__click_button(welcome_btn, "CLOSE_WELCOME")

    def __write_to_textbox(self, text: str, xpath: str, label: str) -> None:
        """Locate a text input by XPath, type `text` into it, then sleep."""
        self.logger.info("Writing to textbox [%s]", label)
        self.logger.debug("XPath: %s", xpath)
        self.driver.find_element(By.XPATH, xpath).send_keys(text)
        self.__sleep()

    def __click_button(self, xpath: str, label: str) -> None:
        """Locate a clickable element by XPath, click it, then sleep."""
        self.logger.info("Clicking button [%s]", label)
        self.logger.debug("XPath: %s", xpath)
        self.driver.find_element(By.XPATH, xpath).click()
        self.__sleep()

    def __sleep(self) -> None:
        """Sleep for a random duration within the configured min/max range to avoid rate-limiting."""
        sleep_time = random.randint(self.config.sleep_time_min, self.config.sleep_time_max)
        self.logger.info("Sleeping for %s seconds", sleep_time)
        time.sleep(sleep_time)

    def __navigate(self, url: str) -> None:
        """Navigate the browser to `url` and sleep once the page loads."""
        self.logger.info("Navigating to %s", url)
        self.driver.get(url)
        self.logger.info("Landed on %s", self.driver.current_url)
        self.__sleep()