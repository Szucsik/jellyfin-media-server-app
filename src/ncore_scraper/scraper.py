import random
import re
import time
import logging
from difflib import SequenceMatcher

from selenium import webdriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from collections import Counter

from torrentool import torrent

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
        self._validate_torrent_titles(torrents)
        torrents = self._process_torrent_data(torrents)
        self._validate_torrent_titles(torrents)
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

            torrents.extend(self._get_torrent_data_from_page(page))

        torrents = self._process_torrent_data(torrents, is_serie=True)
        # self._validate_torrent_titles(torrents)
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

    def _get_torrent_data_from_page(self, page: int) -> list[Torrent]:
        """
        Extract raw torrent data (IMDB links, titles, detail links) from the current page.
        `page` is accepted for future use (e.g., logging) but not used directly.
        """
        torrents = self._generate_torrent_stubs()
        torrent_divs = self._get_torrent_text_divs()
        torrents = self._populate_torrent_details(torrents, torrent_divs)
        final = self._populate_imdb_links(torrents, torrent_divs, page)
        return final
    
    def _get_torrent_text_divs(self) -> list[WebElement]:
        """Extract the raw text divs that contain torrent information."""
        return self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.TORRENT_TEXT_DIV)

    def _generate_torrent_stubs(self) -> list[Torrent]:
        """Create one blank Torrent stub per IMDB link found on the current page."""
        count = len(self.driver.find_elements(
            By.CSS_SELECTOR,
            self.selectors.CssSelectors.BrowsePage.TORRENT_TEXT_DIV)
        )
        return [Torrent() for _ in range(count)]

    def _populate_imdb_links(self, torrents: list[Torrent], torrent_divs: list[WebElement], page: int) -> list[Torrent]:
        """Write the IMDB URL into each Torrent stub in list order."""
        for torrent, div in zip(torrents, torrent_divs):
            if page == 4:
                print('As')
            imdb_elements = div.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.IMDB_LINKS)
            if not imdb_elements:
                self.logger.warning("No IMDB link found for torrent '%s', skipping.", torrent.title)
                torrent.imdb_link = ""
                continue

            href = imdb_elements[0].get_attribute("href")
            if href is None:
                raise ValueError(f"Parse error. IMDB link value of torrent {torrent.title} is empty.")

            torrent.imdb_link = href
            torrent.page = page
        return torrents

    def _populate_torrent_details(self, torrents: list[Torrent], torrent_divs: list[WebElement]) -> list[Torrent]:
        """Write the detail page URL and display title into each Torrent stub."""
        links = [div.find_element(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.TORRENT_DETAIL_LINK) for div in torrent_divs]
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

        i = 0
        max = len(torrents)

        while i < max:
            torrent = torrents[i]
            match = self.ID_PATTERN.search(torrent.detail_link)
            if not match:
                raise ValueError(f"No valid 'id' parameter found in URL: {torrent.detail_link}")

            torrent.torrent_id = int(match.group(1))
            torrent.key = key
            torrent.quality = self._get_torrent_quality(torrent.title)
            torrent.download_link = self.config.get_torrent_download_url(torrent_id=torrent.torrent_id, key=key)

            if torrent.imdb_link == "":
                torrents.pop(i)
                i -= 1
                max -= 1
                continue

            if is_serie:
                seasons = re.findall(r"S(\d{1,2})", torrent.title)
                episodes = re.findall(r"E(\d{1,2})", torrent.title)

                if len(seasons) == 0:
                    torrents.pop(i)
                    i -= 1
                    max -= 1
                    continue

                torrent.season = int(seasons[0])

                if len(seasons) > 1:
                    torrent.season_to = int(seasons[1])

                if len(episodes) > 1:
                    torrent.episode = int(episodes[0])

            i += 1

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

        def keep_most_common_prefix(items: list[Torrent]) -> list[Torrent]:
            # Extract first part of each title
            prefixes = [
                item.title.split('.')[0]
                for item in items
                if isinstance(item.title, str) and item.title
            ]

            if not prefixes:
                return items  # nothing to filter

            # Find most common prefix
            most_common_prefix, _ = Counter(prefixes).most_common(1)[0]

            # Keep only items that match it
            filtered = [
                item for item in items
                if item.title.split('.')[0] == most_common_prefix
            ]

            return filtered
            
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
            series_torrents = keep_most_common_prefix(series_torrents)

            for t in series_torrents:
                if t.imdb_link == "https://dereferer.link/?https://imdb.com/title/tt12637874/":
                 print('As')
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
    # Title consistency validation
    # -------------------------------------------------------------------------

    # Pattern that marks the end of the human-readable title in a
    # dot-separated torrent name.  Matches season/episode tags, quality
    # indicators, years, and common technical keywords.
    _TITLE_STOP_PATTERN = re.compile(
        r'^('
        r'S\d{1,2}(E\d{1,2})?'          # season / episode  (S01, S02E05)
        r'|(?:19|20)\d{2}'               # year              (2024, 1999)
        r'|720p?|1080p?|2160p?|4K'       # quality tags
        r'|UHD|HDR|SDR'
        r'|REPACK|PROPER|INTERNAL'        # release flags
        r'|BluRay|BDRip|BRRip|WEBRip'    # source tags
        r'|WEB-DL|WEBDL|WEB|HDTV|DVDRip'
        r'|AMZN|NF|DSNP|HMAX|ATVP|PCOK' # streaming services
        r'|DDP?\d|AAC|DTS|Atmos|TrueHD'  # audio codecs
        r'|[HhXx]\.?26[45]|HEVC|AVC'    # video codecs
        r'|REMUX|MULTi|HUN|ENG|GER'     # misc tags / languages
        r')$',
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_title(title: str) -> str:
        """
        Extract just the human-readable show/movie name from a torrent title.

        Strategy: split by common separators (`.`, `_`, `-`, space) and keep
        only the parts *before* the first token that looks like a season tag,
        quality indicator, year, or technical keyword.  The remaining parts
        are joined, lowercased, and stripped of non-alphanumeric characters.

        Example:
            'Fallout.S02.720p.AMZN.WEB-DL.DDP5.1.Atmos.H.264.HUN.ENG'
            → 'fallout'
        """
        # Split on dots, underscores, spaces, and hyphens (but keep
        # hyphenated title words like "Spider-Man" together by re-joining
        # later — the stop-pattern check handles the rest).
        parts = re.split(r'[\._\s\-]+', title)

        name_parts: list[str] = []
        for part in parts:
            if Scraper._TITLE_STOP_PATTERN.match(part):
                break
            name_parts.append(part)

        name = ''.join(name_parts).lower()
        # Remove any remaining non-alphanumeric characters
        name = re.sub(r'[^a-z0-9]', '', name)
        return name

    def _validate_torrent_titles(self, torrents: list[Torrent], similarity_threshold: float = 0.80) -> None:
        """
        Verify that torrents sharing the same IMDB link have consistent titles.

        For each IMDB group the most common normalized title is chosen as
        the reference.  If any torrent's normalized title is less than
        `similarity_threshold` (default 80 %) similar to that reference,
        a ValueError is raised with full diagnostic information.
        """

        # --- group by IMDB link ------------------------------------------------
        by_imdb: dict[str, list[Torrent]] = {}
        for torrent in torrents:
            by_imdb.setdefault(torrent.imdb_link, []).append(torrent)

        for imdb_link, group in by_imdb.items():
            if len(group) < 2:
                continue

            # Compute the normalized title for every torrent in the group
            norm_titles = [self._normalize_title(t.title) for t in group]

            # Pick the most frequent normalized title as the reference
            reference_title, _ = Counter(norm_titles).most_common(1)[0]

            for torrent, norm in zip(group, norm_titles):
                ratio = SequenceMatcher(None, reference_title[:5], norm[:5]).ratio()
                if ratio < similarity_threshold:
                    # Build a detailed report of every torrent in the group
                    group_details = "\n".join(
                        f"  - id={t.torrent_id}, title='{t.title}', "
                        f"normalized='{self._normalize_title(t.title)}', "
                        f"quality={t.quality.name}, season={t.season}, "
                        f"detail_link='{t.detail_link}'"
                        for t in group
                    )
                    raise ValueError(
                        f"Title mismatch detected for IMDB link '{imdb_link}'.\n"
                        f"Reference normalized title: '{reference_title}'\n"
                        f"Mismatched torrent: id={torrent.torrent_id}, "
                        f"title='{torrent.title}', normalized='{norm}', "
                        f"similarity={ratio:.1%} (threshold={similarity_threshold:.0%})\n"
                        f"All torrents in this IMDB group:\n{group_details}"
                    )

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
                try:
                    self.logger.info("Dismissing welcome message")
                    self.__click_button(welcome_btn, "CLOSE_WELCOME")
                except Exception as e:  
                    self.logger.error("Failed to dismiss welcome message: %s", e)

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