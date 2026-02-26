from logging import Logger
import os
import requests
import shutil
import re

from pathlib import Path

import torrentool.api as torrentool

from db import Database
from models import Torrent


def download_torrent_files(download_path: str, movies: list[Torrent], logger: Logger) -> list[Torrent]:
    """a"""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://ncore.pro/"
    }

    for movie in movies:
        response = requests.get(movie.download_link, headers=headers)
        path = f"{download_path}/{movie.torrent_id}.torrent"
        movie.torrent_file_location = path

        if response.status_code == 200:
            with open(path, "wb") as f:
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


def generate_series_placeholders(series: list[Torrent], target_directory: str, placeholder_path: str, logger: Logger) -> None:
    """a"""
    video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'}

    for serie in series:
        torrent = torrentool.Torrent.from_file(serie.torrent_file_location)

        for t in torrent.files:
            path = Path(t.name)

            if path.suffix.lower() not in video_extensions:
                continue

            full_target_file = f"{target_directory}/{t.name}"

            directory = Path(target_directory) / path.parent
            directory.mkdir(parents=True, exist_ok=True)

            if not os.path.isfile(full_target_file):
                shutil.copy(src=placeholder_path, dst=f"{full_target_file}")

            serie.downloaded = False
            serie.main_movie_file_path = f"{serie.main_movie_file_path};{full_target_file}"

def generate_symlinks_to_the_placheolders(series: list[Torrent], symlink_directory: str, logger: Logger) -> None:
    """a"""
    season_pattern = re.compile(r"S(\d{1,2})", re.IGNORECASE)
    year_pattern = re.compile(r"(19\d{2}|20\d{2})")
    episode_pattern = re.compile(r"E(\d{1,3})", re.IGNORECASE)


    for serie in series:
        files: list[str] = serie.main_movie_file_path.split(';')

        for file in files:
            diretory_name = Path(file).parent.name

            name = diretory_name.replace(".", " ")

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
            directory.mkdir(parents=True, exist_ok=True)

            if season is not None:
                season_path = Path(directory) / Path(season)
                directory.mkdir(parents=True, exist_ok=True)

                if "sample" in file.lower():
                    continue

                match = episode_pattern.search(file)

                if match:
                    # Extract the digits and format as E01, E02, etc.
                    episode_num = match.group(1).zfill(2)
                    Path(file).symlink_to(season_path / Path(f"E{episode_num}.{Path(file).suffix}"))






def write_new_torrents_to_the_db(movies: list[Torrent]):
    """a"""
    db = Database()
    db.write(movies)


