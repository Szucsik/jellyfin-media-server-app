from config import Configuration
from data_processing.data_processing import DataProcessing
from data_processing.file_processing import FileProcessing
from ncore_scraper.scraper import Scraper


config = Configuration()
scraper = Scraper(username=config.username, password=config.password)

scraper.get_all_hd_torrents(is_show=False, max_pages=20)
scraper.get_all_hd_torrents(is_show=True, max_pages=20)

data_processor = DataProcessing(config=config)
data_processor.process()

file_processor = FileProcessing(logger=config.logger, config=config)
file_processor.process()

# scraper.close()
print('Finished')