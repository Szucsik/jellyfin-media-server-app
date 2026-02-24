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
