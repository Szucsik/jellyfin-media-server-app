import asyncio
import threading

from fastapi import FastAPI

from config import Configuration
from data_processing.data_processing import DataProcessing
from data_processing.file_processing import FileProcessing
from ncore_scraper.scraper import Scraper

app = FastAPI(title="Parsing & File Generation API")

_lock = threading.Lock()
_running = False
_task_thread: threading.Thread | None = None


def _run_parsing_pipeline() -> None:
    global _running

    try:
        config = Configuration()
        logger = config.logger

        logger.info("Parsing pipeline started")

        scraper = Scraper(username=config.username, password=config.password)
        try:
            scraper.get_all_hd_torrents(is_show=False, max_pages=20)
            scraper.get_all_hd_torrents(is_show=True, max_pages=20)
        finally:
            scraper.close()

        data_processor = DataProcessing(config=config)
        data_processor.process()

        file_processor = FileProcessing(logger=logger, config=config)
        file_processor.process()

        logger.info("Parsing pipeline finished")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Parsing pipeline error: %s", exc)
    finally:
        with _lock:
            _running = False


@app.post("/parsing")
def toggle_parsing(enabled: bool) -> dict:
    """Start or stop the parsing / file generation pipeline."""
    global _running, _task_thread

    with _lock:
        if enabled:
            if _running:
                return {"status": "already_running"}
            _running = True
            _task_thread = threading.Thread(target=_run_parsing_pipeline, daemon=True)
            _task_thread.start()
            return {"status": "started"}
        else:
            if not _running:
                return {"status": "already_stopped"}
            _running = False
            return {"status": "stopping"}
