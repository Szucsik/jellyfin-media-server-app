import logging
import os

from models import Torrent
from ncore_scraper.scraper import Scraper
from utils import download_torrent_files, write_new_torrents_to_the_db, generate_symlink_to_placeholders, get_torrent_media_files_information

logging.basicConfig(
    filename='run.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

username = os.getenv("NCORE_USERNAME")
password = os.getenv("NCORE_PASSWORD")

torrent_files_location = os.getenv("TORRENT_FILES_LOCATION")
symlink_series_directory = os.getenv("VOLUME_SERIES_DIR")
symlink_movies_directory = os.getenv("VOLUME_MOVIE_DIR")
placeholders_directory = os.getenv("VOLUME_PLACEHOLDER_TARGET_DIR")
downloaded_directory = os.getenv("VOLUME_DOWNLOADED_DIR")

if username is None or password is None:
    raise ValueError("NCORE_USERNAME or NCORE_PASSWORD is not set")

if torrent_files_location is None:
    raise ValueError("TORRENT_FILES_LOCATION is not set")

if symlink_series_directory is None or symlink_movies_directory is None or placeholders_directory is None or downloaded_directory is None:
    raise ValueError("a")

scraper = Scraper(username=username, password=password)

scraper.login()

hd_movies: list[Torrent] = scraper.get_all_hd_movies()
hd_series: list[Torrent] = scraper.get_all_hd_series(max_pages=11)

def update_list(
    media: list[Torrent],
    torrent_target_loc: str,
    symlink_directory: str,
    placeholder_loc: str,
    is_series: bool
):
    """a"""

    result = download_torrent_files(
        download_path=torrent_target_loc,
        movies=media,
        logger=logger
    )

    result = get_torrent_media_files_information(
        torrents=result,
        target_directory=torrent_target_loc,
        logger=logger
    )

    generate_symlink_to_placeholders (
        result, 
        symlink_directory=symlink_directory,
        placeholder_file_path=f"{placeholder_loc}/jellyfin-placeholder.mp4",
        is_series=is_series,
        logger=logger,
        download_path=torrent_target_loc
    )

    write_new_torrents_to_the_db(media)


update_list(
    media=hd_movies,
    torrent_target_loc=torrent_files_location,
    symlink_directory=symlink_movies_directory,
    placeholder_loc=placeholders_directory,
    is_series=False
)

update_list(
    media=hd_series,
    torrent_target_loc=torrent_files_location,
    symlink_directory=symlink_series_directory,
    placeholder_loc=placeholders_directory,
    is_series=False
)


print('Finished')