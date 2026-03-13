import os
from pathlib import Path
import re
import time

import requests
import torrentool.api as torrentool

from config import Configuration
from data_processing.utils.file_processing_utils import FileProcessingUtils
from models.local_file_information import LocalFileInformation
from models.movie import Movie
from models.show import Show
from models.torrent import Torrent


class FileProcessing:

    def __init__(self, logger, config: Configuration):
        self.logger = logger
        self.config = config

    def process(self):
        """a"""
        self.__download_torrent_files()
        self.__generate_symlink_to_placeholders()
    
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
                        # print('mock')
                        f.write(response.content)
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

        self.config.local_files_repository.save(local_file_information)



    def __generate_symlink_to_placeholders(self) -> None:
        """a"""
        movies: list[Movie] = self.config.movie_repository.get_all()
        shows: list[Show] = self.config.show_repository.get_all()

        self.generate_symlinks_for_movies(movies)
        self.generate_symlinks_for_shows(shows)


    def generate_symlinks_for_shows(self, shows: list[Show]):
        utils = FileProcessingUtils()
        episode_pattern = re.compile(r"E(\d{1,3})", re.IGNORECASE)
        for show in shows:
            seasons = self.config.show_season_repository.get_all_seasons_for_show(show.id)
            for season in seasons:
                associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=season.torrent_id)
                
                local_file: LocalFileInformation = self.config.local_files_repository.find_first_by(torrent_id=associated_torrent.id)
                files: list[str] = local_file.main_media_files_local_path.split(';')

                show_file_formatted = utils.get_show(files)[0]

                match = re.search(r"/title/(tt\d+)", associated_torrent.imdb_link)
                imdb_id = match.group(1)
                show_file_formatted.name += f" [imdbib={imdb_id}]"

                symlink_directory_path = Path(self.config.symlink_series_directory)
                target_directory = Path(symlink_directory_path) / Path(show_file_formatted.name)
                target_directory.mkdir(parents=True, exist_ok=True)
                if "Game.of" in associated_torrent.title:
                    print("'")
                for s in show_file_formatted.seasons:
                    season_path = Path(target_directory) / Path(str(s.number))
                    season_path.mkdir(parents=True, exist_ok=True)

                    for e in s.episodes:
                        symlink_path = season_path / Path(e.filename)

                        if os.path.islink(symlink_path):
                            os.unlink(symlink_path)

                        Path(symlink_path).symlink_to(self.config.placeholder_starter_path)

    def generate_symlinks_for_movies(self, movies: list[Movie]):
        year_pattern = re.compile(r"(19\d{2}|20\d{2})")
        for movie in movies:
            associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=movie.torrent_id)
            local_file: LocalFileInformation = self.config.local_files_repository.find_first_by(torrent_id=associated_torrent.id)
            files: list[str] = local_file.main_media_files_local_path.split(';')

            for file in files:
                file_path_parts = Path(file).parts

                directory_name = file_path_parts[0]
                file_name = file_path_parts[len(file_path_parts)-1]
                subdirectories = ""

                if len(file_path_parts) > 2:    
                    subdirectories = "/".join(file_path_parts[1:len(file_path_parts)-1])


                if "sample" in directory_name.lower() or "sample" in subdirectories.lower() or "sample" in file_name.lower():
                    continue

                name = directory_name.replace(".", " ")

                # --- year ---
                year_match = year_pattern.search(name)
                year = year_match.group(1) if year_match else None

                # --- title ---
                cut_positions = []

                if year_match:
                    cut_positions.append(year_match.start())

                if cut_positions:
                    title = name[:min(cut_positions)]
                else:
                    title = name

                title = title.strip()
            
                # Add year to the title if exists, DISABLED: because of inconsistencies (e.g. for only one seasons it has the year in the title)
                if year:
                    title += f" ({year})"

                # Add the metadata provider to the title
                match = re.search(r"/title/(tt\d+)", associated_torrent.imdb_link)
                imdb_id = match.group(1)
                title += f" [imdbib={imdb_id}]"

                # Create series directory if not exists
                symlink_directory_path = Path(self.config.symlink_movies_directory)

                target_directory = Path(symlink_directory_path) / Path(title)
                if subdirectories != "":
                    target_directory = target_directory / Path(subdirectories)

                if Path(self.config.torrent_files_location).name in target_directory.name:
                    target_directory = Path(symlink_directory_path) / Path(Path(file).stem + f" [imdbib={imdb_id}]")

                target_directory.mkdir(parents=True, exist_ok=True)

                symlink_path = Path(target_directory) / Path(file).name

                if os.path.islink(symlink_path):
                    os.unlink(symlink_path)

                Path(symlink_path).symlink_to(self.config.placeholder_starter_path)
            
