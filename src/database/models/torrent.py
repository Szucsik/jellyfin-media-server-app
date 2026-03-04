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
    detail_link: str = ""
    key: str = ""
    is_show: bool = False
    category: str = ""
   