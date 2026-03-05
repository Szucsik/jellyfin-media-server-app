from typing import Optional
from sqlalchemy import Column, Integer, ForeignKey
from sqlmodel import SQLModel, Field


class MovieTorrent(SQLModel, table=True):
    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    torrent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("torrent.id"))
    )