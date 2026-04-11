import os
from pathlib import Path
import re

import requests
import torrentool.api as torrentool
import httpx
import asyncio

from config import Configuration
from models.local_file_information import LocalFileInformation
from models.movie import Movie
from models.show import Show
from models.torrent import Torrent
from ncore_scraper.config import ScraperConfig


class FileProcessing:
    """This class is responsible for making file operations so the Jellyfin and the 
    qBittorrent can access and load the media files and the torrents later"""
    def __init__(self, config: Configuration):
        self.config = config
        self.logger = config.get_logger(__name__)

        self.client: httpx.AsyncClient = httpx.AsyncClient(
            headers={"User-Agent": "python ncoreparser"}, timeout=30, follow_redirects=True
        )

        self.client.cookies.clear()
        self.scraper_config = ScraperConfig()

    async def process(self):
        """Start the file processing"""

        await self.__download_torrent_files()
        self.__generate_symlink_to_placeholders()

    async def download_torrent_by_id(self, id: int):
        """Download torrent files by torrent id, not ncore torrent id but torrent ids from the database"""
        associated_torrent: Torrent = self.config.torrent_repository.find_first_by(torrent_id=id)
        path = f"{self.config.torrent_files_location}/{associated_torrent.torrent_id}.torrent"
        if not os.path.exists(path):
            self.logger.info("Starting to download torrent: %s", associated_torrent.title)
            max_tries = 100
            current_tries = 0
            response_status = False

            while current_tries < max_tries:
                try:
                    self.logger.info("Trying to download")
                    response = requests.get(associated_torrent.download_link, headers=headers)
                    if response.status_code == 200:
                        response_status = True
                        break
                    else:
                        self.logger.info("Non-200 response (%s), attempt: %s/%s", response.status_code, current_tries, max_tries)
                except:
                    self.logger.info("Download failed, attempt: %s/%s", current_tries, max_tries)

                current_tries += 1
                wait_time = 5 * current_tries
                self.logger.info("Waiting: %s seconds", wait_time)
                await asyncio.sleep(wait_time)

            if not response_status:
                self.logger.error("Couldn't download torrent: %s", associated_torrent.title)
                raise Exception(f"Couldn't download torrent: {associated_torrent.title}")

            with open(path, "wb") as f:
                f.write(response.content)
            self.logger.info("Torrent downloaded successfully. %s out of %s", torrents_list.index(associated_torrent), len(torrents_list))

        else:
            self.logger.info("Torrent file already exists:%s | %s", associated_torrent.title, associated_torrent.torrent_id)

        self.__get_torrent_media_file_information(path=path, torrent=associated_torrent)

    
    async def __download_torrent_files(self):
        """Download all torrent files that are in the database and if they are not exists"""
        self.logger.info("Download torrents process started")
        
        movies: list[Movie] = self.config.movie_repository.get_all()
        shows: list[Show] = self.config.show_repository.get_all()

        torrents_list: list[Torrent] = []

        for show in shows:
            seasons = self.config.show_season_repository.get_all_seasons_for_show(show.id)
            for season in seasons:
                associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=season.torrent_id)
                torrents_list.append(associated_torrent)

        self.logger.info("Show torrents collected: %s", len(torrents_list))
        for movie in movies:
            associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=movie.torrent_id)
            torrents_list.append(associated_torrent)

        self.logger.info("Movie torrents collected: %s", len(movies))

        for associated_torrent in torrents_list:
            path = f"{self.config.torrent_files_location}/{associated_torrent.torrent_id}.torrent"
            if not os.path.exists(path):
                self.logger.info("Starting to download torrent: %s", associated_torrent.title)
                max_tries = 100
                current_tries = 0
                status_code = 0

                while current_tries < max_tries:
                    try:
                        status_code = await self.__download_torrent_file(associated_torrent, path)
                    except Exception as e:
                        self.logger.error("Download failed, attempt: %s/%s %s", current_tries, max_tries, e)

                    if status_code != 200:
                        self.logger.error("Couldn't download torrent: %s", associated_torrent.title)
                       
                    else:
                        break;

                    current_tries += 1
                    wait_time = 5 * current_tries
                    self.logger.info("Waiting: %s seconds", wait_time)
                    await asyncio.sleep(wait_time)

                if current_tries == max_tries:
                     raise Exception(f"Couldn't download torrent: {associated_torrent.title}")


                self.logger.info("Torrent downloaded successfully. %s out of %s", torrents_list.index(associated_torrent), len(torrents_list))

            else:
                self.logger.info("Torrent file already exists:%s | %s", associated_torrent.title, associated_torrent.torrent_id)

            self.__get_torrent_media_file_information(path=path, torrent=associated_torrent)

    async def __download_torrent_file(self, torrent: Torrent, target_path: str) -> int:
        """Method for downloading the torrent file using httpx client"""
        while not await self.__is_logged_in():
            try:
                self.logger.info("HTTPX not logged in. Try to log in.")
                login_data = {"nev": self.config.username, "pass": self.config.password, "set_lang": "hu", "submitted": "1", "ne_leptessen_ki": "1"}

                await self.client.post(self.scraper_config.login_url, data=login_data)
            except Exception as e:
                self.logger.error("Error while performing post method to url '%s'. Exception: %s", torrent.download_link, e)
                await asyncio.sleep(10)

        try:
            self.logger.info("HTTPX client will start to download this torrent: %s", torrent.download_link)
            content = await self.client.get(torrent.download_link)
        except Exception as e:
            self.logger.error("Error while downloading torrent. Url: %s", torrent.download_link)
            raise Exception(f"Error while downloading torrent. Url: '{torrent.download_link}'. {e}") from e

        if os.path.exists(target_path):
            return 200

        with open(target_path, "wb") as fh:
            self.logger.info("Writing torrent file to target location: %s", target_path)
            fh.write(content.content)

        return content.status_code

        

    async def __is_logged_in(self):
        """Check if the httpx client is logged in to the ncore.pro web page"""
        r = await self.client.get(self.scraper_config.home_url)
        if "login.php" in str(r.url) or "<title>nCore</title>" in r.text:
            return False
        return True

    def __get_torrent_media_file_information(self, path: str, torrent: Torrent) -> None:
        """Load the torrent file and check the what media files does the torrent has"""
        local_file_information = LocalFileInformation(
            torrent_id=torrent.id,
            torrent_file_local_path=path
        )

        self.logger.info("Processing torrent file: %s", torrent.title)

        try:
            torrent_information = torrentool.Torrent.from_file(path)
        except Exception as e:
            self.logger.error("Couldn't open torrent file. Removing torrent %s %s. Exception: %s", torrent.title, torrent.torrent_id, e)
            if torrent.is_show:
                self.config.show_season_repository.delete_by_torrent_id(torrent_id=torrent.id)
            else:
                self.config.movie_repository.delete_by_torrent_id(torrent_id=torrent.id)

            self.config.torrent_repository.delete_by_id(torrent.id)
            return None

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

        self.config.local_files_repository.save_if_new(local_file_information)

    def __generate_symlink_to_placeholders(self) -> None:
        """Generate symlinks for movies and shows."""
        movies: list[Movie] = self.config.movie_repository.get_all()
        shows: list[Show] = self.config.show_repository.get_all()

        self.logger.info("Starting to generate symlink placeholders")
        self.generate_symlinks_for_movies(movies)
        self.generate_symlinks_for_shows(shows)

    def generate_symlinks_for_shows(self, shows: list[Show]):
        """This method is used for generating symlinks to a placeholder media file for every show, season and episode"""
        utils = FileProcessingUtils()
        for show in shows:
            target_directory = ""
            seasons = self.config.show_season_repository.get_all_seasons_for_show(show.id)

            self.logger.info("Processing show: %s", show.id)
            for season in seasons:
                associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=season.torrent_id)

                self.logger.info("Processing season %s", associated_torrent.title)
                
                local_file: LocalFileInformation = self.config.local_files_repository.find_first_by(torrent_id=associated_torrent.id)
                files: list[str] = local_file.main_media_files_local_path.split(';')

                show_file_formatted_array = utils.get_show(files)

                if len(show_file_formatted_array) == 0:
                    continue

                show_file_formatted = utils.get_show(files)[0]

                # For shows thats title is a year like 1923, we want to keep the year in the title
                if show_file_formatted.name is None and show_file_formatted.year is not None:
                    show_file_formatted.name = f"{show_file_formatted.year}"
                # For shows that have a name and a year, we want to keep the year in the title
                elif show_file_formatted.year is not None:
                    show_file_formatted.name += f" ({show_file_formatted.year})"

                match = re.search(r"/title/(tt\d+)", associated_torrent.imdb_link)
                if match is None:
                    self.logger.error("Can't find imdb id inside imdb link using regex. Torrent name: %s; Torrent id: %s, IMDB url: %s",
                    associated_torrent.title, associated_torrent.id, associated_torrent.imdb_link)
                    raise ValueError("Can't find imdb id inside imdb link using regex.")

                imdb_id = match.group(1)
                show_file_formatted.name += f" [imdbid-{imdb_id}]"

                symlink_directory_path = Path(self.config.symlink_series_directory)
                if target_directory == "":
                    target_directory = Path(symlink_directory_path) / Path(show_file_formatted.name)
                target_directory.mkdir(parents=True, exist_ok=True)
                
                symlink_paths: list[str] = []
                original_paths: list[str] = []
                for s in show_file_formatted.seasons:
                    season_path = Path(target_directory) / Path(f"Season {str(s.number)}")
                    season_path.mkdir(parents=True, exist_ok=True)

                    for e in s.episodes:
                        symlink_path = season_path / Path(e.filename)

                        if os.path.islink(symlink_path):
                            os.unlink(symlink_path)

                        Path(symlink_path).symlink_to(self.config.placeholder_starter_path)
                        symlink_paths.append(str(symlink_path))
                        original_paths.append(e.original_path)

                local_file.symlink_path = ";".join(symlink_paths)
                local_file.original_file_path = ";".join(original_paths)
                self.config.local_files_repository.save(local_file)

    def generate_symlinks_for_movies(self, movies: list[Movie]):
        """This method is used for generating symlinks to a placeholder media file for every movie"""
        year_pattern = re.compile(r"(19\d{2}|20\d{2})")
        for movie in movies:
            associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=movie.torrent_id)

            assert associated_torrent.id is not None

            self.logger.info("Processing movie: %s", associated_torrent.title)

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
                if match:
                    imdb_id = match.group(1)
                else:
                    # handle the case where no match is found
                    self.logger.error("No imdb string found in %s. Torrent id: %r", associated_torrent.title, associated_torrent.torrent_id)
                    continue
                
                title += f" [imdbid-{imdb_id}]"

                # Create series directory if not exists
                symlink_directory_path = Path(self.config.symlink_movies_directory)

                target_directory = Path(symlink_directory_path) / Path(title)
                if subdirectories != "":
                    target_directory = target_directory / Path(subdirectories)

                if Path(self.config.torrent_files_location).name in target_directory.name:
                    target_directory = Path(symlink_directory_path) / Path(Path(file).stem + f" [imdbid-{imdb_id}]")

                target_directory.mkdir(parents=True, exist_ok=True)

                symlink_path = Path(target_directory) / Path(file).name

                if os.path.islink(symlink_path):
                    os.unlink(symlink_path)

                Path(symlink_path).symlink_to(self.config.placeholder_starter_path)

                local_file.symlink_path = str(symlink_path)
                local_file.original_file_path = file
                self.config.local_files_repository.save(local_file)
            
