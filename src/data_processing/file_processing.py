import os
import shutil
from pathlib import Path
import re

import torrentool.api as torrentool
import httpx
import asyncio
import time
from datetime import datetime

from config import Configuration
from models.local_file_information import LocalFileInformation
from data_processing.utils.file_processing_utils import FileProcessingUtils
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
            headers={"User-Agent": "python ncoreparser"}, timeout=300, follow_redirects=True
        )

        self.client.cookies.clear()
        self.scraper_config = ScraperConfig()

    async def process(self):
        """Start the file processing"""

        await self.__download_torrent_files()
        self.__generate_symlink_to_placeholders()

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
            path = f"{self.config.torrent_files_target_location}/{associated_torrent.torrent_id}.torrent"
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
            target_file = ";".join(t.name for t in torrent_information.files)
        else:
            target_file = max(torrent_information.files, key=lambda t: t.length).name

        local_file_information.main_media_files_local_path = target_file

        self.config.local_files_repository.save_if_new(local_file_information)

    def __generate_symlink_to_placeholders(self) -> None:
        """Generate symlinks for movies and shows."""
        movies: list[Movie] = self.config.movie_repository.get_all()
        shows: list[Show] = self.config.show_repository.get_all()

        self.logger.info("Starting to generate symlink placeholders")
        self.generate_symlinks_for_movies(movies)
        self._cleanup_stray_top_level_season_dirs()
        self.generate_symlinks_for_shows(shows)

    def _cleanup_stray_top_level_season_dirs(self) -> None:
        """Remove buggy top-level season folders directly under the series root.

        These folders are invalid because Jellyfin show layout must be:
        <series root>/<Show Name>/Season N/<episode file>.
        """
        root = Path(self.config.symlink_series_directory)
        if not root.exists():
            return

        season_dir_pattern = re.compile(r"^Season\s+\d+$")
        removed = 0

        for child in root.iterdir():
            if not child.is_dir():
                continue
            if not season_dir_pattern.match(child.name):
                continue

            self.logger.warning("Removing stray top-level season directory: %s", child)
            shutil.rmtree(child, ignore_errors=True)
            removed += 1

        if removed > 0:
            self.logger.warning("Removed %s stray top-level season directories under %s", removed, root)

    def _get_skipped_shows_report_path(self) -> Path:
        """Return the report file path for skipped shows."""
        return Path(self.config.torrent_files_target_location) / "skipped_shows_report.tsv"

    def _append_skipped_show_report(
        self,
        show: Show,
        season,
        torrent: Torrent,
        imdb_id: str,
        reason: str,
    ) -> None:
        """Append one skipped show entry to the report file."""
        report_path = self._get_skipped_shows_report_path()
        report_path.parent.mkdir(parents=True, exist_ok=True)

        torrent_file_name = f"{torrent.torrent_id}.torrent"
        torrent_file_path = Path(self.config.torrent_files_target_location) / torrent_file_name

        header = (
            "timestamp\tshow_id\tseason_id\tseason\tseason_to\ttorrent_db_id\ttorrent_ncore_id"
            "\ttorrent_title\ttorrent_download_link\timdb_id\ttorrent_file_name\ttorrent_file_path\treason\n"
        )
        row = (
            f"{datetime.utcnow().isoformat()}Z\t"
            f"{show.id}\t"
            f"{season.id}\t"
            f"{season.season}\t"
            f"{season.season_to}\t"
            f"{torrent.id}\t"
            f"{torrent.torrent_id}\t"
            f"{torrent.title}\t"
            f"{torrent.download_link}\t"
            f"{imdb_id}\t"
            f"{torrent_file_name}\t"
            f"{torrent_file_path}\t"
            f"{reason}\n"
        )

        write_header = not report_path.exists() or report_path.stat().st_size == 0
        with report_path.open("a", encoding="utf-8") as report_file:
            if write_header:
                report_file.write(header)
            report_file.write(row)


    def generate_symlinks_for_shows(self, shows: list[Show]):
        """This method is used for generating symlinks to a placeholder media file for every show, season and episode"""
        utils = FileProcessingUtils()
        skipped_shows: list[str] = []
        report_path = self._get_skipped_shows_report_path()
        for show in shows:
            seasons = self.config.show_season_repository.get_all_seasons_for_show(show.id)

            target_directory = ""

            # Has to sleep because of the TMDB API limitations (40/second)
            time.sleep(0.025)
            
            self.logger.info("Processing show: %s", show.id)
            for season in seasons:
                associated_torrent: Torrent = self.config.torrent_repository.find_first_by(id=season.torrent_id)

                self.logger.info("Processing season %s", associated_torrent.title)
                
                local_file: LocalFileInformation = self.config.local_files_repository.find_first_by(torrent_id=associated_torrent.id)
                files: list[str] = local_file.main_media_files_local_path.split(';')

                show_file_formatted_array = utils.get_show(files)

                if len(show_file_formatted_array) == 0:
                    continue

                show_file_formatted = show_file_formatted_array[0]

                # Add the metadata provider to the title
                match = re.search(r"/title/(tt\d+)", associated_torrent.imdb_link)
                if match:
                    imdb_id = match.group(1)
                else:
                    # handle the case where no match is found
                    self.logger.error("No imdb string found in %s. Torrent id: %r", associated_torrent.title, associated_torrent.torrent_id)
                    continue

                if target_directory == "":
                    show_name = utils.get_name_by_id_from_tmdb(imdb_id=imdb_id, api_key=self.config.tmdb_api_key)  # IMDB ID is the same for all the seasons!
                    if not show_name:
                        self.logger.warning(
                            "TMDB name lookup failed for imdb_id=%s (torrent: %s). Skipping show.",
                            imdb_id,
                            associated_torrent.title,
                        )
                        skipped_shows.append(f"{associated_torrent.title} [imdbid-{imdb_id}]")
                        self._append_skipped_show_report(
                            show=show,
                            season=season,
                            torrent=associated_torrent,
                            imdb_id=imdb_id,
                            reason="TMDB name lookup failed",
                        )
                        break
                    self.logger.info("Name of the show has been queried from TMDB API: %s", show_name)
                    target_directory = Path(self.config.symlink_series_directory) / Path(show_name)

                target_directory.mkdir(parents=True, exist_ok=True)
                
                symlink_paths: list[str] = []
                original_paths: list[str] = []
                expected_seasons: set[int] = set()
                if season.season > 0:
                    if season.season_to > 0:
                        expected_seasons.update(range(season.season, season.season_to + 1))
                    else:
                        expected_seasons.add(season.season)

                parsed_seasons = show_file_formatted.seasons
                if expected_seasons:
                    parsed_seasons = [s for s in parsed_seasons if s.number in expected_seasons]

                for s in parsed_seasons:
                    season_path = Path(target_directory) / Path(f"Season {str(s.number)}")
                    season_path.mkdir(parents=True, exist_ok=True)

                    for e in s.episodes:
                        symlink_path = season_path / Path(e.filename)

                        if not os.path.islink(symlink_path):
                            #os.unlink(symlink_path)
                            Path(symlink_path).symlink_to(self.config.placeholder_starter_path)
                            
                        symlink_paths.append(str(symlink_path))
                        original_paths.append(e.original_path)

                local_file.symlink_path = ";".join(symlink_paths)
                local_file.original_file_path = ";".join(original_paths)
                self.config.local_files_repository.save(local_file)

        if skipped_shows:
            self.logger.warning(
                "Skipped %d show(s) because TMDB name lookup failed. Report file: %s\n%s",
                len(skipped_shows),
                report_path,
                "\n".join(f"  - {s}" for s in skipped_shows),
            )

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

                # Subdirectories: directories between the root directory and the media files
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

                if Path(self.config.torrent_files_target_location).name in target_directory.name:
                    target_directory = Path(symlink_directory_path) / Path(Path(file).stem + f" [imdbid-{imdb_id}]")

                target_directory.mkdir(parents=True, exist_ok=True)

                symlink_path = Path(target_directory) / Path(file).name

                if not os.path.islink(symlink_path):
                    #os.unlink(symlink_path)
                    Path(symlink_path).symlink_to(self.config.placeholder_starter_path)

                local_file.symlink_path = str(symlink_path)
                local_file.original_file_path = file
                self.config.local_files_repository.save(local_file)
            
