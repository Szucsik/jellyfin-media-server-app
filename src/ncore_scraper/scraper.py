import random
import time
import logging
import re

from selenium import webdriver
from selenium.webdriver.common.by import By

from ncore_scraper.config import ScraperConfig
from ncore_scraper.models import Torrent, Quality
from ncore_scraper.selectors import ScraperSelectors

class Scraper:
    """Ncore.pro scraper agent"""

    logged_in = False
    torrents = list[Torrent]

    def __init__(self, username: str, password: str) -> None:
        """Scraper init"""

        self.logger = logging.getLogger(__name__)
        self.logger.info('Scraper initialized')

        self.username = username
        self.password = password

        self.config = ScraperConfig()
        self.selectors = ScraperSelectors()
        self.driver = webdriver.Firefox(self.config.driver_options)

    
    def login(self):
        """Login to ncore.pro and then start fresh on the home page"""
        self.logger.info('Login method started')
        self._open_login_page()
        self._submit_credentials()
        self._handle_post_login_redirections()
        self.logged_in = True


    def get_all_hd_movies(self):
        """s"""
        self._open_browse_hd_movie_page()
        current_page = 1
        max = 5
        torrents: list[Torrent] = []
        self.__navigate(self.config.get_browse_hd_pages_url(current_page))
        while(self.driver.find_elements(By.XPATH, self.selectors.Xpaths.BrowsePage.TEXT_NOT_FOUND_LIST) and current_page < max):
            torrents += self._get_torrent_data_from_page(current_page)
            current_page += 1
            self.__navigate(self.config.get_browse_hd_pages_url(current_page))

        torrents = self._process_torrent_data(torrents)
        print('ffs')

    subtitle: str = ""
    def _open_login_page(self):
        """Navigate to the login page"""
        self.__navigate(self.config.login_url)

        # Check if the login elements are loaded
        while(
            not self.driver.find_elements(By.XPATH, self.selectors.Xpaths.LoginPage.TEXTBOX_USERNAME) or
            not self.driver.find_elements(By.XPATH, self.selectors.Xpaths.LoginPage.TEXTBOX_PASSWORD) or
            not self.driver.find_elements(By.XPATH, self.selectors.Xpaths.LoginPage.BUTTON_LOGIN)
        ):
            self.logger.warning('Webdriver navigation was unsuccessful, the login expected are not present. Retrying...')
            self.driver.get(self.config.login_url)
            self.__sleep()

    def _open_browse_hd_movie_page(self):
        """Navigate to the login page"""
        self.__navigate(self.config.browse_hd_url)       

        # Check if the login elements are loaded
        while(
            not self.driver.find_elements(By.XPATH, self.selectors.Xpaths.BrowsePage.BUTTON_SORT_BY_SEEDERS) or
            not self.driver.find_elements(By.XPATH, self.selectors.Xpaths.BrowsePage.CHECKBOX_HDHUN_FILTER) or
            not self.driver.find_elements(By.XPATH, self.selectors.Xpaths.BrowsePage.TEXTBOX_SEARCH_FIELD)
        ):
            self.logger.warning('Webdriver navigation was unsuccessful, the expected elements are not present. Retrying...')
            self.driver.get(self.config.browse_hd_url)
            self.__sleep()

    def _process_torrent_data(self, all_torrents: list[Torrent]) -> list[Torrent]:
        key: str = self._get_key_from_ncore()
        for torrent in all_torrents:
            match = re.search(r"id=(\d+)", torrent.detail_link)
            if match:
                torrent.id = int(match.group(1))
            else:
                raise ValueError("URL does not contain a valid integer 'id' parameter")

            torrent.key = key
            torrent.quality = self._get_torrent_quality(torrent.title)

        return all_torrents

    def _get_key_from_ncore(self) -> str:
        """a"""
        key_pattern = r'<link rel="alternate" href=".*?\/rss.php\?key=(?P<key>[a-z,0-9]+)" title=".*"'
        match = re.search(key_pattern,self.driver.page_source)
        if match:
            return match.group(1)
        else:
            raise ValueError("Can't get the key for the torrent downloads")

    def _get_torrent_quality(self, title: str) -> Quality:
        """a"""
        for quality in Quality:
            if quality == Quality.UNASSIGNED:
                pass
            if quality.value in title:
                return quality

        return Quality.UNASSIGNED


    def _get_torrent_data_from_page(self, page: int) -> list[Torrent]:
        """a"""
        torrents: list[Torrent] = self._generate_torrent_list()
        torrents = self._get_imdb_links(torrents)
        torrents = self._get_torrent_details(torrents)

        return torrents

    def _generate_torrent_list(self) -> list[Torrent]:
        torrents: list[Torrent] = []
        for _ in self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.IMDB_LINKS):
            torrents.append(Torrent())

        return torrents

    def _get_imdb_links(self, page_torrents: list[Torrent])-> list[Torrent]:
        """test"""
        links = self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.IMDB_LINKS)
        i = 0
        for link in links:
            page_torrents[i].imdb_link = str(link.get_attribute("href"))
            i += 1

        return page_torrents

    def _get_torrent_details(self, page_torrents: list[Torrent])-> list[Torrent]:
        """test"""
        links = self.driver.find_elements(By.CSS_SELECTOR, self.selectors.CssSelectors.BrowsePage.TORRENT_DETAIL_LINK)
        i = 0
        for link in links:
            page_torrents[i].detail_link = str(link.get_attribute("href"))
            page_torrents[i].title = str(link.text)
            i += 1

        return page_torrents    


    def _submit_credentials(self) -> None:
        """Fill login form and submit."""
        self.__write_to_textbox(text=self.username, xpath=self.selectors.Xpaths.LoginPage.TEXTBOX_USERNAME, log="LOGIN_USERNAME")
        self.__write_to_textbox(text=self.password, xpath=self.selectors.Xpaths.LoginPage.TEXTBOX_PASSWORD, log="LOGIN_PASSWORD")
        self.__click_button(xpath=self.selectors.Xpaths.LoginPage.BUTTON_LOGIN, log="LOGIN_LOGINBUTTON")


    def _handle_post_login_redirections(self):
        """Handle post login redirections and pop-ups"""
        if self.driver.current_url == self.config.premium_shop_url:
            self.logger.info('Detected: redirected to premium page')
            self.__click_button(xpath=self.selectors.Xpaths.HomePage.BUTTON_HOME_PAGE_FROM_PREMIUM, log="HOME_PREMIUM_BACK_TO_HOME_BUTTON")

        if self.driver.current_url == self.config.login_url:
            self.logger.error('Login failed')

        if self.driver.current_url == self.config.home_url:
            if self.driver.find_elements(By.XPATH, self.selectors.Xpaths.HomePage.BUTTON_WELLCOME_MESSAGE_CLOSE):
                self.logger.info('Detected: wellcome message in the home page')
                self.__click_button(self.selectors.Xpaths.HomePage.BUTTON_WELLCOME_MESSAGE_CLOSE, log="HOME_CLOSE_WELLCOME_MESSAGE_BUTTON")

    def __write_to_textbox(self, text: str, xpath: str, log: str):
        """Standardized method of writing text to a textbox using the webdriver"""
        self.logger.info('Writing to textbox: %s', log)
        self.logger.debug('Used xpath: %s', xpath)
        self.driver.find_element(By.XPATH, xpath).send_keys(text)
        self.__sleep()

    def __click_button(self, xpath: str, log: str):
        """Standardized method of clicking an element using the webdriver"""
        self.logger.info('Clicking on button: %s', log)
        self.logger.debug('Used xpath: %s', xpath)
        self.driver.find_element(By.XPATH, xpath).click()
        self.__sleep()
    
    def __sleep(self):
        """Sleeping a few seconds before the next action"""
        sleep_time = random.randint(self.config.sleep_time_min, self.config.sleep_time_max)
        time.sleep(sleep_time)
        self.logger.info('Sleeping before the next step, time: %s', sleep_time)

    def __navigate(self, url: str):
        self.logger.info('Starting navigate to %s', url)
        self.driver.get(url)
        self.logger.info('Webdriver navigated to %s', self.driver.current_url)
        self.__sleep()