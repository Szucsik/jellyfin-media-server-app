from fastapi import FastAPI

from config import Configuration
from data_processing.data_processing import DataProcessing
from data_processing.file_processing import FileProcessing
from ncore_scraper.scraper import Scraper

app = FastAPI(title="Parsing & File Generation API")
config = Configuration()
logger = config.logger

@app.post("/parsing")
async def toggle_parsing(pages: int) -> str:
    """Start or stop the parsing / file generation pipeline."""
    logger.info("Parsing pipeline started")

    scraper = Scraper(username=config.username, password=config.password)

    try:
        logger.info("Scraping HD movies started")
        scraper.get_all_hd_torrents(is_show=False, max_pages=pages)

        logger.info("Scraping HD shows started")
        scraper.get_all_hd_torrents(is_show=True, max_pages=pages)
    finally:
        logger.info("Close webdriver")
        scraper.close()

    logger.info("Data processor started")
    data_processor = DataProcessing(config=config)
    data_processor.process()

    logger.info("File processor started")
    file_processor = FileProcessing(logger=logger, config=config)
    await file_processor.process()

    logger.info("Parsing pipeline finished")

    return "Parsing pipeline finished"


@app.post("/processing")
async def trigger_processing_stages() -> str:
    """Start or stop the parsing / file generation pipeline."""
    logger.info("Data processor started")
    data_processor = DataProcessing(config=config)
    data_processor.process()

    logger.info("File processor started")
    file_processor = FileProcessing(logger=logger, config=config)
    await file_processor.process()

    logger.info("Processing pipeline finished")

    return "Processing pipeline finished"

@app.post("/download-torrent")
async def download_torrents() -> str:
    """Start downloading torrent by"""
    logger.info("Torrents download processor started")
    file_processor = FileProcessing(logger=logger, config=config)
    await file_processor.process()

    logger.info("Torrents download pipeline finished")

    return "Torrents download pipeline finished"


# @app.post("/download-torrent-by-id")
# def download_torrent_By_id(id: int) -> str:
#     """Start downloading torrent by id. The torrent and the download URL must be in the database."""
#     config = Configuration()
#     logger = config.logger

#     logger.info("Torrent downloading started")
#     file_processor = FileProcessing(logger=logger, config=config)
#     file_processor.download_torrent_by_id(id=id)

#     logger.info("Torrent downloaded %s", id)

#     return "Torrentfile downloaded"