from logging import Logger
import os
import requests
import shutil
from pathlib import Path

import torrentool.api as torrentool

from db import Database
from models import Torrent


def download_torrent_files(download_path: str, movies: list[Torrent], torrent_files_location: str, logger: Logger) -> list[Torrent]:
    """a"""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://ncore.pro/"
    }

    for movie in movies:
        response = requests.get(movie.download_link, headers=headers)
        download_path = f"{torrent_files_location}/{movie.torrent_id}.torrent"
        movie.torrent_file_location = download_path

        if response.status_code == 200:
            with open(download_path, "wb") as f:
                f.write(response.content)
            logger.info("Torrent downloaded successfully.")
        else:
            logger.error("Torrent downloaded failed: %s", movie.title)

    return movies

def generate_placeholders(movies: list[Torrent], target_directory: str, placeholder_path: str, logger: Logger) -> None:
    """a"""
    for movie in movies:
        torrent = torrentool.Torrent.from_file(movie.torrent_file_location)

        names: list[str] = []
        sizes: list[int] = []

        for t in torrent.files:
            names.append(t.name)
            sizes.append(t.length)

        max_size = 0
        for size in sizes:
            max_size = max(max_size, size)

        target_file = names[sizes.index(max_size)]
        path = Path(target_file)

        full_target_file = f"{target_directory}/{target_file}"

        directory = Path(target_directory) / path.parent
        directory.mkdir(parents=True, exist_ok=True)

        if not os.path.isfile(full_target_file):
            shutil.copy(src=placeholder_path, dst=f"{full_target_file}")

        movie.downloaded = False
        movie.main_movie_file_path = full_target_file

def write_new_torrents_to_the_db(movies: list[Torrent]):
    """a"""
    db = Database()
    db.write(movies)


