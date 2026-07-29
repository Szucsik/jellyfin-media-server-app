from dataclasses import dataclass
from enum import Enum
from selenium.webdriver.firefox.options import Options


# @dataclass(frozen=True)
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

    class ScanTypes(Enum):
        REFRESH = "refresh"
        FULL_SCAN = "full_scan"

    class Languages(Enum):
        ENG = "eng"
        HUN = "hun"

    class MediaTypeTags(Enum):
        HD_MOVIE = "hd"
        HD_SHOW = "hdser"
        SD_MOVIE = "xvid"
        SD_SHOW = "xvidser"

    browse_sort_types = {
        "refresh": "ctime",
        "full_scan": "seeders"
    }

    scan_type: ScanTypes = ScanTypes.FULL_SCAN.value

    def __get_type_tag(self, media_type: MediaTypeTags, language: Languages) -> str:
        lang_tag: str = "_hun" if language == self.Languages.HUN else ""
        return media_type.value + lang_tag

    def get_browse_url(self, page: int, type: MediaTypeTags, lang: Languages) -> str:
        """Return the url for HD show page with a specified page number"""
        return f"{self.browse_url}?oldal={page}&tipus=kivalasztottak_kozott&kivalasztott_tipus={self.__get_type_tag(type, lang)}&miszerint={self.browse_sort_types[self.scan_type]}&hogyan=DESC"

    def get_torrent_download_url(self, torrent_id: int, key: str) -> str:
        """Return download torrent file link based on torrent id and user key"""
        return f"{self.browse_url}?action=download&id={str(torrent_id)}&key={key}"
