from config import Configuration
from data_processing.data_processing import DataProcessing
from database.db import TorrentRepository
from models.torrent import Torrent
from ncore_scraper.scraper import Scraper




config = Configuration()
scraper = Scraper(username=config.username, password=config.password)

hd_movies: list[Torrent] = scraper.get_all_hd_torrents(is_show=False, max_pages=2)
hd_series: list[Torrent] = scraper.get_all_hd_torrents(is_show=True, max_pages=2)

data_processor = DataProcessing()
data_processor.process()

# def update_list(
#     media: list[Torrent],
#     torrent_target_loc: str,
#     symlink_directory: str,
#     placeholder_loc: str,
#     is_series: bool
# ):
#     """a"""

#     result = download_torrent_files(
#         download_path=torrent_target_loc,
#         movies=media,
#         logger=logger
#     )

#     result = get_torrent_media_files_information(
#         torrents=result,
#         target_directory=torrent_target_loc,
#         logger=logger
#     )

#     generate_symlink_to_placeholders (
#         result, 
#         symlink_directory=symlink_directory,
#         placeholder_file_path=f"{placeholder_loc}/jellyfin-placeholder.mp4",
#         is_series=is_series,
#         logger=logger,
#         download_path=torrent_target_loc
#     )

#     write_new_torrents_to_the_db(media)


# update_list(
#     media=hd_movies,
#     torrent_target_loc=torrent_files_location,
#     symlink_directory=symlink_movies_directory,
#     placeholder_loc=placeholders_directory,
#     is_series=False
# )

# update_list(
#     media=hd_series,
#     torrent_target_loc=torrent_files_location,
#     symlink_directory=symlink_series_directory,
#     placeholder_loc=placeholders_directory,
#     is_series=False
# )

scraper.close()
print('Finished')