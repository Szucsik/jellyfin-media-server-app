from dataclasses import dataclass


class ScraperSelectors:
    """Web selectors for the ncore.pro webpage"""
    class Xpaths:
        """XPath selectors for the ncore.pro torrent webpage"""

        @dataclass(frozen=True)
        class LoginPage():
            """XPath selectors for the login page"""
            TEXTBOX_USERNAME = '/html/body/div[1]/div/div[1]/form/table/tbody/tr[1]/td[2]/input'
            TEXTBOX_PASSWORD = '/html/body/div[1]/div/div[1]/form/table/tbody/tr[2]/td[2]/input'
            BUTTON_LOGIN = '/html/body/div[1]/div/div[1]/form/table/tbody/tr[1]/td[3]/input'

        @dataclass(frozen=True)
        class HomePage():
            """XPath selectors for the home page"""
            BUTTON_HOME_PAGE_FROM_PREMIUM = '/html/body/app-root/app-base-page/div/div[1]/div/div[1]/div[1]/div[2]/div[1]/a[1]'
            BUTTON_WELLCOME_MESSAGE_CLOSE = '/html/body/div[1]/div/div[3]/span[2]'
            BUTTON_BROWSE_TORRENTS_BUTTON = '/html/body/div[1]/div/div[1]/div[3]/div/div[2]/div[4]/a'

        @dataclass(frozen=True)
        class BrowsePage():
            """XPath selectors for the browse torrents page"""
            BUTTON_SORT_BY_SEEDERS = '/html/body/div[1]/div/div[1]/div[5]/div/div[2]/div[2]/div[4]/div[6]/table/tbody/tr/td[2]/div/a'
            CHECKBOX_HDHUN_FILTER = '/html/body/div[1]/div/div[1]/div[5]/div/div[2]/div[1]/div[5]/div[1]/form/div[1]/table/tbody/tr/td[14]/input'
            TEXTBOX_SEARCH_FIELD = '/html/body/div[1]/div/div[1]/div[5]/div/div[2]/div[1]/div[5]/div[1]/form/center/table/tbody/tr[1]/td[2]/input'
            TEXT_NOT_FOUND_LIST = '/html/body/div[1]/div/div[1]/div[5]/div/div[2]/div[2]/div[5]/div[2]'

    @dataclass(frozen=True)
    class CssSelectors:
        """Css selectors for the ncore.pro torrent webpage"""
        
        @dataclass(frozen=True)
        class BrowsePage():
            """Css selectors for the browse torrents page """
            TORRENT_TEXT_DIV = "div.torrent_txt"
            IMDB_LINKS = "a.infolink"
            TORRENT_DETAIL_LINK = "div.torrent_txt > a[href*='action=details']"
            TEXT_NOT_FOUND_LIST = '.lista_mini_error'