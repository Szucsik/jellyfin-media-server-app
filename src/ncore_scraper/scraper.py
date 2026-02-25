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

    def get_all_hd_series(self, max_pages: int = 5) -> list[Torrent]:
        """
        Collect HD serie torrents across multiple browse pages.

        Iterates through paginated results, stopping either when no more
        results are found or when `max_pages` is reached.
        """

        torrents: list[Torrent] = []
        for page in range(1, max_pages + 1):
            self.__navigate(self.config.get_browse_hd_series_url(page))

            # Stop if the "no results" indicator is absent (i.e., results exist)
            if not self.driver.find_elements(By.XPATH, self.selectors.Xpaths.BrowsePage.TEXT_NOT_FOUND_LIST):
                break

            torrents.extend(self._get_torrent_data_from_page())

        torrents = self._process_torrent_data(torrents, is_serie=True)
        torrents = self._distillation_serie_torrent_data(torrents)
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
        torrents = self._populate_torrent_details(torrents)
        torrents = self._populate_imdb_links(torrents)
        return torrents

    def _generate_torrent_stubs(self) -> list[Torrent]:
        """Create one blank Torrent stub per IMDB link found on the current page."""
        count = len(self.driver.find_elements(
            By.CSS_SELECTOR,
            self.selectors.CssSelectors.BrowsePage.IMDB_LINKS)
        )
        return [Torrent() for _ in range(count)]

    def _populate_imdb_links(self, torrents: list[Torrent]) -> list[Torrent]:
        """Write the IMDB URL into each Torrent stub in list order."""
        links = self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.IMDB_LINKS)
        for torrent, link in zip(torrents, links):
            href = link.get_attribute("href")
            if href is None:
                raise ValueError(f"Parse error. IMDB link value of torrent {torrent.title} is empty.")

            torrent.imdb_link = href
        return torrents

    def _populate_torrent_details(self, torrents: list[Torrent]) -> list[Torrent]:
        """Write the detail page URL and display title into each Torrent stub."""
        links = self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.TORRENT_DETAIL_LINK)
        for torrent, link in zip(torrents, links):
            href = link.get_attribute("href")
            if href is None:
                raise ValueError(f"Parse error. Torrent detail link value of torrent {torrent.title} is empty.")

            torrent.detail_link = href
            torrent.title = link.text
        return torrents

    def _process_torrent_data(self, torrents: list[Torrent], is_serie = False) -> list[Torrent]:
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

            if is_serie:
                seasons = re.findall(r"S(\d{1,2})", torrent.title)
                episodes = re.findall(r"E(\d{1,2})", torrent.title)

                if len(seasons) == 0:
                    continue

                torrent.season = int(seasons[0])

                if len(seasons) > 1:
                    torrent.season_to = int(seasons[1])

                if len(episodes) > 1:
                    torrent.episode = int(episodes[0])

        return torrents

    def _distillation_torrent_data(self, torrents: list[Torrent], is_serie = False) -> list[Torrent]:
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

    def _distillation_serie_torrent_data(self, torrents: list[Torrent]) -> list[Torrent]:
        """
        For each series (grouped by IMDB link), produce one Torrent per season.
        Preference order:
        1. Single-season torrents over multi-season packs
        2. Higher quality wins (SD=720 < HD=1080 < UHD=2160),
            but prefer lower quality over UNASSIGNED.
        """

        # --- helpers -----------------------------------------------------------

        def quality_rank(t: Torrent) -> int:
            """Lower rank = more preferred (we use min-selection)."""
            order = {
                Quality.SD:         1,   # 720p  – most preferred
                Quality.HD:         2,   # 1080p
                Quality.UHD:        3,   # 2160p
                Quality.UNASSIGNED: 99,  # always last
            }
            return order.get(t.quality, 99)

        def is_single_season(t: Torrent) -> bool:
            return t.season_to == -1 and t.season > 0
        
        def is_an_episode(t: Torrent) -> bool:
            match = re.search(r'E(\d+)', torrent.title)
            return match == None

        def covers_season(t: Torrent, season: int) -> bool:
            """True when this torrent contains the given season number."""
            if is_single_season(t):
                return t.season == season
            # multi-season pack: season_from..season_to
            if t.season > 0 and t.season_to > 0:
                return t.season <= season <= t.season_to
            return False

        def better(challenger: Torrent, current: Torrent) -> bool:
            """
            Returns True if challenger should replace current.
            Single-season always beats multi-season pack.
            Within the same 'tier', lower quality_rank wins.
            """
            challenger_single = is_single_season(challenger)
            current_single    = is_single_season(current)

            if challenger_single and not current_single:
                return True   # single-season beats pack
            if not challenger_single and current_single:
                return False  # never replace single with pack

            # same tier → compare quality
            return quality_rank(challenger) < quality_rank(current)

        # --- group by series ---------------------------------------------------

        # imdb_link -> list of torrents for that series
        by_series: dict[str, list[Torrent]] = {}
        for torrent in torrents:
            if torrent.season <= 0:        # skip torrents with no season info
                continue
            by_series.setdefault(torrent.imdb_link, []).append(torrent)

        # --- pick one torrent per (series, season) -----------------------------

        result: list[Torrent] = []

        for imdb_link, series_torrents in by_series.items():
            # Find every season number that appears across all torrents
            all_seasons: set[int] = set()

            for t in series_torrents:
            
                if is_an_episode(t):
                    continue

                if is_single_season(t):
                    all_seasons.add(t.season)
                elif t.season > 0 and t.season_to > 0:
                    all_seasons.update(range(t.season, t.season_to + 1)) # Todo: kell a +1?

            # For each season pick the best torrent
            for season in sorted(all_seasons):
                candidates = [t for t in series_torrents if covers_season(t, season)]
                if not candidates:
                    continue

                best = candidates[0]
                for candidate in candidates[1:]:
                    if better(candidate, best):
                        best = candidate

                result.append(best)

        return result

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