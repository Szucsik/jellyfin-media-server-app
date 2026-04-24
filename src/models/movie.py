from typing import Optional
from sqlalchemy import Column, Integer, ForeignKey
from sqlmodel import SQLModel, Field


class Movie(SQLModel, table=True):
    """Table that contains the movie and the related torrent id"""
    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    torrent_id: int = Field(
        default=-1,
        sa_column=Column(Integer, ForeignKey("torrent.id"))
    )