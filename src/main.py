import logging
import os

from models import Torrent
from ncore_scraper.scraper import Scraper
from utils import download_torrent_files, generate_placeholders, write_new_torrents_to_the_db

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

if username is None or password is None:
    raise ValueError("NCORE_USERNAME or NCORE_PASSWORD is not set")

if torrent_files_location is None:
    raise ValueError("TORRENT_FILES_LOCATION is not set")


scraper = Scraper(username=username, password=password)

scraper.login()

hd_movies: list[Torrent] = scraper.get_all_hd_movies()

hd_movies = download_torrent_files(
    download_path=torrent_files_location,
    movies=hd_movies,
    torrent_files_location=torrent_files_location,
    logger=logger
)

generate_placeholders(
    hd_movies,
    target_directory="/home/szucsiki/Documents/Projects/jellyfin-server/srv/jellyfin/media/movies/",
    placeholder_path="/home/szucsiki/Videos/jellyfin-placeholder.mp4",
    logger=logger
)

write_new_torrents_to_the_db(hd_movies)

print('Finished')