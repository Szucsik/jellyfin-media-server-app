from typing import Optional
from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlmodel import SQLModel, Field


class ShowSeason(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "torrent_id",
            "season",
            "season_to",
            "show_id",
            name="uq_show_season_identity",
        ),
    )

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
    show_id: int = -1