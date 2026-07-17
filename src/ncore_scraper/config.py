from dataclasses import dataclass
from selenium.webdriver.firefox.options import Options


@dataclass(frozen=True)
class ScraperConfig:
    """Config class for the scraper service"""
    home_url: str = "https://ncore.pro/index.php"
    login_url: str = "https://ncore.pro/login.php"
    browse_url: str = "https://ncore.pro/torrents.php"
    premium_shop_url: str = "https://ncore.pro/en/shop"
    browse_hd_url: str = "https://ncore.pro/torrents.php?tipus=kivalasztottak_kozott&kivalasztott_tipus=hd_hun&miszerint=seeders&hogyan=DESC"
    
    driver_options = Options()
    driver_options.add_argument("-headless")

    sleep_time_min: int = 2
    sleep_time_max: int = 7



    browse_sort_types = {
        "refresh": "ctime",
        "full_scan": "seeders"
    }

    scan_type = "full_scan"

    def get_browse_hd_movies_url(self, page: int) -> str:
        """Return the url for HD movies page with a specified page number"""
        return f"{self.browse_url}?oldal={page}&tipus=kivalasztottak_kozott&kivalasztott_tipus=hd_hun&miszerint={self.browse_sort_types[self.scan_type]}&hogyan=DESC"

    def get_browse_hd_shows_url(self, page: int) -> str:
        """Return the url for HD show page with a specified page number"""
        return f"{self.browse_url}?oldal={page}&tipus=kivalasztottak_kozott&kivalasztott_tipus=hdser_hun&miszerint={self.browse_sort_types[self.scan_type]}&hogyan=DESC"

    def get_browser_sd_movies_url(self, page: int) -> str:
        """a"""
        return f"{self.browse_url}?oldal={page}&tipus=kivalasztottak_kozott&kivalasztott_tipus=xvid_hun&miszerint=ctime&hogyan=DESC"

    def get_browser_sd_shows_url(self, page: int) -> str:
        """a"""
        return f"{self.browse_url}?oldal={page}&tipus=kivalasztottak_kozott&kivalasztott_tipus=xvidser_hun&miszerint=ctime&hogyan=DESC"

    def get_torrent_download_url(self, torrent_id: int, key: str) -> str:
        """Return download torrent file link based on torrent id and user key"""
        return f"{self.browse_url}?action=download&id={str(torrent_id)}&key={key}"
