from logging import Logger
import os
from os.path import islink
import requests
import shutil
import re
import time

from pathlib import Path

from sqlalchemy.schema import DropColumnComment
import torrentool.api as torrentool

from database.db import Db
from database.models.torrent import Torrent


def download_torrent_files(download_path: str, movies: list[Torrent], logger: Logger) -> list[Torrent]:
    """a"""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://ncore.pro/"
    }

    for movie in movies:
        path = f"{download_path}/{movie.torrent_id}.torrent"
        movie.torrent_file_location = path
        if not os.path.exists(path):
            response = requests.get(movie.download_link, headers=headers)
            time.sleep(1)
            if response.status_code == 200:
                with open(path, "wb") as f:
                    f.write(response.content)
                logger.info("Torrent downloaded successfully.")
            else:
                logger.error("Torrent downloaded failed: %s", movie.title)

    return movies


def get_torrent_media_files_information(torrents: list[Torrent], target_directory: str, logger: Logger) -> list[Torrent]:
    """a"""
    for torrent in torrents:
        torrent_information = torrentool.Torrent.from_file(torrent.torrent_file_location)

        names: list[str] = []
        sizes: list[int] = []

        for t in torrent_information.files:
            names.append(t.name)
            sizes.append(t.length)

        max_size = 0
        for size in sizes:
            max_size = max(max_size, size)

        target_file = names[sizes.index(max_size)]
        torrent.main_movie_file_path = f"{target_directory}/{target_file}"

    return torrents



def generate_symlink_to_placeholders(torrents: list[Torrent], symlink_directory: str, placeholder_file_path: str, download_path: str, is_series: bool, logger: Logger) -> None:
    """a"""

    season_pattern = re.compile(r"S(\d{1,2})", re.IGNORECASE)
    year_pattern = re.compile(r"(19\d{2}|20\d{2})")
    episode_pattern = re.compile(r"E(\d{1,3})", re.IGNORECASE)

    for torrent in torrents:
        files: list[str] = torrent.main_movie_file_path.split(';')

        for file in files:
            directory_name = Path(file).parent.name
            name = directory_name.replace(".", " ")

            # --- season ---
            season_match = season_pattern.search(name)
            season = season_match.group(1) if season_match else None

            # --- year ---
            year_match = year_pattern.search(name)
            year = year_match.group(1) if year_match else None

            # --- title ---
            cut_positions = []

            if season_match:
                cut_positions.append(season_match.start())
            if year_match:
                cut_positions.append(year_match.start())

            if cut_positions:
                title = name[:min(cut_positions)]
            else:
                title = name

            title = title.strip()


            # Create series directory if not exists

            directory = Path(symlink_directory) / Path(title)

            if Path(download_path).name in directory.name:
                directory = Path(symlink_directory) / Path(Path(file).stem)
            directory.mkdir(parents=True, exist_ok=True)

            if is_series:
                if season is not None:
                    season_path = Path(directory) / Path(season)
                    season_path.mkdir(parents=True, exist_ok=True)

                    if "sample" in file.lower():
                        continue

                    match = episode_pattern.search(file)

                    if match:
                        # Extract the digits and format as E01, E02, etc.
                        episode_num = match.group(1).zfill(2)
                        symlink_path = season_path / Path(f"E{episode_num}.{Path(file).suffix}")

                        if os.path.islink(symlink_path):
                            os.unlink(symlink_path)

                        Path(symlink_path).symlink_to(placeholder_file_path)
            else:
                symlink_path = Path(directory) / Path(file).name

                if os.path.islink(symlink_path):
                    os.unlink(symlink_path)

                if "Üveg" in symlink_path.name:
                    print('s')

                Path(symlink_path).symlink_to(placeholder_file_path)


def write_new_torrents_to_the_db(movies: list[Torrent]):
    """a"""
    db = Db('a')
    db.write_torrents(movies)


