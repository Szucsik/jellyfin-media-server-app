from typing import Optional
from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import SQLModel, Field


class LocalFileInformation(SQLModel, table=True):
    id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )
    torrent_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("torrent.id"))
    )
    torrent_file_local_path: Optional[str] = Field(default=None)
    main_media_files_local_path: Optional[str] = Field(default=None)
    original_file_path: Optional[str] = Field(default=None)
    symlink_path: Optional[str] = Field(default=None)