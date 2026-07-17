from fastapi import FastAPI

from config import Configuration
from data_processing.data_processing import DataProcessing
from data_processing.file_processing import FileProcessing
from ncore_scraper.scraper import Scraper

app = FastAPI(title="Parsing & File Generation API")
config = Configuration()
logger = config.get_logger(__name__)

@app.post("/full-parsing")
async def toggle_full_parsing() -> str:
    """Start or stop the parsing / file generation pipeline."""
    logger.info("Parsing pipeline started")
    pages = 9999999
    config.scan_type = "full_scan"
    scraper = Scraper(username=config.username, password=config.password, config=config)

    try:
        logger.info("%s Scraping HD movies started %s", '-' * 20, '-' * 20)
        scraper.get_all_torrents(is_show=False, is_hd=True, max_pages=pages)

        logger.info("%s Scraping SD movies started %s", '-' * 20, '-' * 20)
        scraper.get_all_torrents(is_show=False, is_hd=False, max_pages=pages)

        logger.info("%s Scraping HD shows started %s", '-' * 20, '-' * 20)
        scraper.get_all_torrents(is_show=True, is_hd=True, max_pages=pages)

        logger.info("%s Scraping SD shows started %s", '-' * 20, '-' * 20)
        scraper.get_all_torrents(is_show=True, is_hd=False, max_pages=pages)
    finally:
        logger.info("Close webdriver")
        scraper.close()

    logger.info("Data processor started")
    data_processor = DataProcessing(config=config)
    data_processor.process()

    logger.info("File processor started")
    file_processor = FileProcessing(config=config)
    await file_processor.process()

    logger.info("Parsing pipeline finished")

    return "Parsing pipeline finished"

@app.post("/parsing")
async def toggle_parsing(pages: int) -> str:
    """Start or stop the parsing / file generation pipeline."""
    logger.info("Parsing pipeline started")
    config.scan_type = "refresh"
    scraper = Scraper(username=config.username, password=config.password, config=config)

    try:
        logger.info("%s Scraping HD movies started %s", '-' * 20, '-' * 20)
        scraper.get_all_torrents(is_show=False, is_hd=True, max_pages=pages)

        logger.info("%s Scraping SD movies started %s", '-' * 20, '-' * 20)
        scraper.get_all_torrents(is_show=False, is_hd=False, max_pages=pages)

        logger.info("%s Scraping HD shows started %s", '-' * 20, '-' * 20)
        scraper.get_all_torrents(is_show=True, is_hd=True, max_pages=pages)

        logger.info("%s Scraping SD shows started %s", '-' * 20, '-' * 20)
        scraper.get_all_torrents(is_show=True, is_hd=False, max_pages=pages)
    finally:
        logger.info("Close webdriver")
        scraper.close()

    logger.info("Data processor started")
    data_processor = DataProcessing(config=config)
    data_processor.process()

    logger.info("File processor started")
    file_processor = FileProcessing(config=config)
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
    file_processor = FileProcessing(config=config)
    await file_processor.process()

    logger.info("Processing pipeline finished")

    return "Processing pipeline finished"

@app.post("/download-torrent")
async def download_torrents() -> str:
    """Start downloading torrent by"""
    logger.info("Torrents download processor started")
    file_processor = FileProcessing(config=config)
    await file_processor.process()

    logger.info("Torrents download pipeline finished")

    return "Torrents download pipeline finished"


#     return "Torrentfile downloaded"