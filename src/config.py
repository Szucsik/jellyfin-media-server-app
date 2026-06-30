import logging
import os

from database.db import LocalFilesRepository, MovieRepository, ShowRepository, ShowSeasonsRepository, TorrentRepository


class LineCappedFileHandler(logging.FileHandler):
    """File handler that keeps only the latest `max_lines` lines."""

    def __init__(self, filename: str, max_lines: int = 1000):
        super().__init__(filename)
        self.max_lines = max_lines

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        with open(self.baseFilename, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > self.max_lines:
            with open(self.baseFilename, "w", encoding="utf-8") as f:
                f.writelines(lines[-self.max_lines:])


class Configuration:
    """Configuration class for environment variables and logging."""

    # Init logger: keep only the latest 1000 lines in run.log.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            LineCappedFileHandler('run.log', max_lines=1000),
            logging.StreamHandler(),
        ],
    )

    logger = logging.getLogger(__name__)

    def get_logger(self, name: str) -> logging.Logger:
        """Return a module-scoped logger."""
        return logging.getLogger(name)

    # Db repositories
    torrent_repository = TorrentRepository()
    movie_repository = MovieRepository()
    show_season_repository = ShowSeasonsRepository()
    show_repository = ShowRepository()
    local_files_repository = LocalFilesRepository()

    # Ncore variables
    username = os.getenv("NCORE_USERNAME")
    password = os.getenv("NCORE_PASSWORD")

    # Filesystem variables
    torrent_files_location = os.getenv("TORRENT_FILES_LOCATION")
    torrent_files_target_location = os.getenv("TORRENT_FILES_TARGET_LOCATION")
    symlink_series_directory = os.getenv("VOLUME_SERIES_DIR")
    symlink_movies_directory = os.getenv("VOLUME_MOVIE_DIR")
    placeholders_directory = os.getenv("VOLUME_PLACEHOLDER_TARGET_DIR")
    downloaded_directory = os.getenv("VOLUME_DOWNLOADED_DIR")
    downloaded_target_directory = os.getenv("VOLUME_DOWNLOADED_TARGET_DIR")

    # Jellyfin server variables
    jellyfin_url = os.getenv("JELLYFIN_URL")
    jellyfin_user_id = os.getenv("JELLYFIN_USER_ID")
    jellyfin_api_key = os.getenv("JELLYFIN_API_KEY")

    # TMDB
    tmdb_api_key = os.getenv("TMDB_API_KEY")

    # qBittorrent variables
    qbittorrent_host = os.getenv("QBITTORRENT_HOST")
    qbittorrent_port = os.getenv("QBITTORRENT_PORT")
    qbittorrent_username = os.getenv("QBITTORRENT_USERNAME")
    qbittorrent_password = os.getenv("QBITTORRENT_PASSWORD")

    # Checks
    if username is None or password is None:
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

    # Placeholders
    placeholder_starter_path = placeholders_directory + "/jellyfin-placeholder.mp4"
    placeholder_one_hr_left_path = placeholders_directory + "/jellyfin-placeholder-1-hour-left.mp4"
    placeholder_less_then_one_hr_left_path = placeholders_directory + "/jellyfin-placeholder-less-then-1-hour-left.mp4"
    placeholder_half_hr_left_path = placeholders_directory + "/jellyfin-placeholder-half-hour-left.mp4"
    placeholder_less_then_twenty_min_left_path = placeholders_directory + "/jellyfin-placeholder-less-then-20-minutes-left.mp4"
    placeholder_less_then_ten_min_left_path = placeholders_directory + "/jellyfin-placeholder-less-then-10-minutes-left.mp4"
    placeholder_less_then_five_min_left_path = placeholders_directory + "/jellyfin-placeholder-less-then-5-minutes-left.mp4"
    placeholder_less_then_a_few_min_left_path = placeholders_directory + "/jellyfin-placeholder-less-then-a-few-minutes-left.mp4"

    def __init__(self):
        pass
