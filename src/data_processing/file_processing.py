import os
import time

import requests
import torrentool

from database.db import LocalFilesRepository, MovieRepository, ShowRepository, ShowSeasonsRepository, TorrentRepository
from models import movie
from models.local_file_information import LocalFileInformation
from models.movie import Movie
from models.show import Show
from models.show_season import ShowSeason
from models.torrent import Torrent


class FileProcessing:

    def __init__(self, logger, download_path: str, local_files_repository: LocalFilesRepository, show_repository: ShowRepository, show_season_repository: ShowSeasonsRepository, movie_repository: MovieRepository, torrent_repository: TorrentRepository):
        self.logger = logger
        self.download_path = download_path
        self.local_files_repository = local_files_repository
        self.torrent_repository = torrent_repository
        self.show_repository = show_repository
        self.show_season_repository = show_season_repository
        self.movie_repository = movie_repository

    def process(self):
        """a"""
        self.__download_torrent_files()
    
    def __download_torrent_files(self):
        """a"""
        movies: list[Movie] = self.movie_repository.get_all()
        shows: list[Show] = self.show_repository.get_all()

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://ncore.pro/"
        }

        torrents_list: list[Torrent] = []

        for show in shows:
            seasons = self.show_season_repository.get_all_seasons_for_show(show.id)
            for season in seasons:
                associated_torrent: Torrent = self.torrent_repository.find_first_by(id=season.torrent_id)
                torrents_list.append(associated_torrent)

        for movie in movies:
            associated_torrent: Torrent = self.torrent_repository.find_first_by(id=movie.torrent_id)
            torrents_list.append(associated_torrent)

        for associated_torrent in torrents_list:
            path = f"{self.download_path}/{associated_torrent.torrent_id}.torrent"
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