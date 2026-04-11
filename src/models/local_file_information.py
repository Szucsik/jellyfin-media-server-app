from typing import Optional
from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlmodel import SQLModel, Field


class LocalFileInformation(SQLModel, table=True):
    """Database table that contains information about the files and locations of a torrent"""
    __table_args__ = (
        UniqueConstraint("torrent_id", name="uq_local_file_torrent_id"),
    )

    id: Optional[int] = Field(
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    torrent_id: int = Field(
        default=-1,
        sa_column=Column(Integer, ForeignKey("torrent.id"))
    )
    torrent_file_local_path: str = Field(default="")
    main_media_files_local_path: str = Field(default="")
    original_file_path: str = Field(default="")
    symlink_path: str = Field(default="")
