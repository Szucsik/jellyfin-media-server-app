import os
from pathlib import Path
import re
import time

import requests
import torrentool

from config import Configuration
from database.db import LocalFilesRepository, MovieRepository, ShowRepository, ShowSeasonsRepository, TorrentRepository
from models import movie
from models.local_file_information import LocalFileInformation
from models.movie import Movie
from models.show import Show
from models.show_season import ShowSeason
from models.torrent import Torrent


class FileProcessing:

    def __init__(self, logger, config: Configuration):
        self.logger = logger
        self.config = config

    def process(self):
        """a"""
        self.__download_torrent_files()
    
    def __download_torrent_files(self):
        """a"""
        movies: list[Movie] = self.config.movie_repository.get_all()
        shows: list[Show] = self.config.show_repository.get_all()

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://ncore.pro/"
        }

        torrents_list: list[Torrent] = []

        for show in shows:
            seasons = self.config.show_season_repository.get_all_seasons_for_show(show.id)
            for season in seasons:
                associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=season.torrent_id)
                torrents_list.append(associated_torrent)

        for movie in movies:
            associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=movie.torrent_id)
            torrents_list.append(associated_torrent)

        for associated_torrent in torrents_list:
            path = f"{self.config.torrent_files_location}/{associated_torrent.torrent_id}.torrent"
            if not os.path.exists(path):
                response = requests.get(associated_torrent.download_link, headers=headers)

                if response.status_code == 200:
                    with open(path, "wb") as f:
                        print('mock')
                        # f.write(response.content)
                    self.__get_torrent_media_file_information(path=path, torrent=associated_torrent)
                    self.logger.info("Torrent downloaded successfully.")
                else:
                    self.logger.error("Torrent downloaded failed: %s", associated_torrent.torrent_id)

                    time.sleep(1)

        def __get_torrent_media_file_information(self, path: str, torrent: Torrent) -> None:
            """a"""
            local_file_information = LocalFileInformation(
                torrent_id=torrent.id,
                torrent_file_local_path=path
            )
            torrent_information = torrentool.Torrent.from_file(path)

            if torrent.is_show:
                target_file = ""
                for t in torrent_information.files:
                    if target_file == "":
                        target_file = t.name
                    else:
                        target_file += f";{t.name}"
                    break
            else:
                names: list[str] = []
                sizes: list[int] = []

                for t in torrent_information.files:
                    names.append(t.name)
                    sizes.append(t.length)

                max_size = 0
                for size in sizes:
                    max_size = max(max_size, size)

                target_file = names[sizes.index(max_size)]

            local_file_information.main_media_files_local_path = target_file

    def __generate_symlink_to_placeholders(self, torrents: list[Torrent]) -> None:
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

                directory = Path(self.config.symlink_directory) / Path(title)

                if Path(self.config.torrent_files_location).name in directory.name:
                    directory = Path(self.config.symlink_directory) / Path(Path(file).stem)
                directory.mkdir(parents=True, exist_ok=True)

                if torrent.is_show and season is not None:
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

                        Path(symlink_path).symlink_to(self.config.placeholder_starter_path)
                else:
                    symlink_path = Path(directory) / Path(file).name

                    if os.path.islink(symlink_path):
                        os.unlink(symlink_path)

                    if "Üveg" in symlink_path.name:
                        print('s')

                    Path(symlink_path).symlink_to(self.config.placeholder_starter_path)
