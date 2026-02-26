from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Field


class Quality(Enum):
    """a"""
    UNASSIGNED =  "UNASSIGNED"
    SD = "720"
    HD = "1080"
    UHD = "2160"

class Torrent(SQLModel, table=True):
    """Data model for the basic ncore.pro Torrent"""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = ""
    imdb_link: str = ""
    quality: Quality = Quality.UNASSIGNED
    detail_link: str = ""
    download_link: str = ""
    torrent_id: int = -1
    key: str = ""
    torrent_file_location: str = ""
    downloaded: bool = False
    main_movie_file_path: str = ""
    symlink_path: str = ""

    # Serie data
    season: int = -1
    season_to: int = -1
    episode: int = -1

class SerieForDistillation():
    """a"""
    imdb_link: str = ""
    
    __seasons: list[int] = []

    def compare_seasons(self, seasons_from: int, seasons_to: int) -> bool:
        """a"""

        seasons: list[int] = []
        for season in range(seasons_from, seasons_to):
            seasons.append(season)

        


    def add_season(self, season: int) -> bool:
        """a"""

        if season not in self.__seasons:
            self.__seasons.append(season)
            self.__seasons.sort()
            return True
        else:
            return False

    def get_seasons(self) -> list[int]:
        """a"""

        return self.__seasons

    