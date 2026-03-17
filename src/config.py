import logging
import os

from database.db import LocalFilesRepository, MovieRepository, ShowRepository, ShowSeasonsRepository, TorrentRepository


class Configuration:
    """Configuration class for environment variables and logging."""
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler('run.log'),
            logging.StreamHandler(),
        ],
    )

    torrent_repository = TorrentRepository()
    movie_repository = MovieRepository()
    show_season_repository = ShowSeasonsRepository()
    show_repository = ShowRepository()
    local_files_repository = LocalFilesRepository()

    logger = logging.getLogger(__name__)

    username = os.getenv("NCORE_USERNAME")
    password = os.getenv("NCORE_PASSWORD")

    torrent_files_location = os.getenv("TORRENT_FILES_LOCATION")
    symlink_series_directory = os.getenv("VOLUME_SERIES_DIR")
    symlink_movies_directory = os.getenv("VOLUME_MOVIE_DIR")
    placeholders_directory = os.getenv("VOLUME_PLACEHOLDER_TARGET_DIR")
    downloaded_directory = os.getenv("VOLUME_DOWNLOADED_DIR")

    jellyfin_url = os.getenv("JELLYFIN_URL")
    jellyfin_user_id = os.getenv("JELLYFIN_USER_ID")
    jellyfin_api_key = os.getenv("JELLYFIN_API_KEY")

    qbittorrent_host = os.getenv("QBITTORRENT_HOST")
    qbittorrent_port = os.getenv("QBITTORRENT_PORT")
    qbittorrent_username = os.getenv("QBITTORRENT_USERNAME")
    qbittorrent_password = os.getenv("QBITTORRENT_PASSWORD")

    if username is None or username == "" or password is None or password == "":
        raise ValueError("NCORE_USERNAME or NCORE_PASSWORD is not set")

    if torrent_files_location is None:
        raise ValueError("TORRENT_FILES_LOCATION is not set")

    if symlink_series_directory is None \
        or symlink_movies_directory is None \
        or  placeholders_directory is None \
        or downloaded_directory is None \
        or jellyfin_user_id is None \
        or jellyfin_api_key is None \
        or jellyfin_user_id is None \
        or qbittorrent_host is None \
        or qbittorrent_port is None \
        or qbittorrent_username is None \
        or qbittorrent_password is None:
        raise ValueError("One or more directory environment variables are not set")
    

    placeholder_starter_path = placeholders_directory + "/jellyfin-placeholder.mp4"

    def __init__(self):
        pass
