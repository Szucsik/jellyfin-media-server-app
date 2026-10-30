from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlmodel import SQLModel, Field


class SubtitleDownload(SQLModel, table=True):
    """Tracks Hungarian subtitle downloads per Jellyfin item.

    One row per Jellyfin movie / episode item. Used both to avoid re-downloading
    a subtitle that is already present and to enforce the provider's per-day
    download limit (the number of rows with ``status == "downloaded"`` and a
    ``downloaded_at`` on the current day).
    """

    __table_args__ = (
        UniqueConstraint("jellyfin_item_id", name="uq_subtitle_download_item_id"),
    )

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True),
    )
    jellyfin_item_id: str = Field(sa_column=Column(String, nullable=False))
    torrent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("torrent.id"), nullable=True),
    )
    imdb_id: str = Field(default="")
    name: str = Field(default="")
    language: str = Field(default="hun")
    # pending / downloaded / already_present / not_found / failed
    status: str = Field(default="pending")
    downloaded_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
