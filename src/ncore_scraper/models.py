from enum import Enum
from pydantic import BaseModel


class Quality(Enum):
    """a"""
    UNASSIGNED =  "UNASSIGNED"
    SD = "720"
    HD = "1080"
    UHD = "2160"


class Torrent(BaseModel):
    """a"""
    title: str = ""
    imdb_link: str = ""
    quality: Quality = Quality.UNASSIGNED
    detail_link: str = ""
    id: int = -1
    key: str = ""
