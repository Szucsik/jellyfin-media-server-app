from typing import Optional
from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import SQLModel, Field


class ShowTorrent(SQLModel, table=True):
    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    torrent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("torrent.id"))
    )
    season: int = -1
    season_to: int = -1