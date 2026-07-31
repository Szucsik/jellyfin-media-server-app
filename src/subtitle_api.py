import threading
from typing import Optional

from fastapi import FastAPI

from config import Configuration
from subtitle_service import SubtitleUpdateService

app = FastAPI(title="Jellyfin Subtitle Update API")

_lock = threading.Lock()
_running = False
_task_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_last_result: Optional[dict] = None
_config = Configuration()
_logger = _config.get_logger(__name__)


def _start_worker() -> bool:
    """Start the subtitle worker thread. Returns True if started, False if already running."""
    global _running, _task_thread
    with _lock:
        if _running:
            return False
        _running = True
        _stop_event.clear()
        _task_thread = threading.Thread(target=_run_update, daemon=True)
        _task_thread.start()
        return True


def _run_update() -> None:
    global _running, _last_result
    logger = _logger

    try:
        logger.info("Subtitle update worker thread started")
        service = SubtitleUpdateService(config=_config)
        _last_result = service.run(stop_event=_stop_event)
        logger.info("Subtitle update worker finished: %s", _last_result)
    except Exception as exc:
        logger.exception("Subtitle update error: %s", exc)
    finally:
        with _lock:
            _running = False
        logger.info("Subtitle update worker thread stopped")


@app.post("/update-subtitles")
def toggle_update_subtitles(enabled: bool = True) -> dict:
    """Start (enabled=true) or stop (enabled=false) the Hungarian subtitle update run."""
    global _running

    _logger.info("/update-subtitles called with enabled=%s", enabled)

    with _lock:
        currently_running = _running

    if enabled:
        if currently_running:
            _logger.info("Subtitle update already running; ignoring start request")
            return {"status": "already_running"}
        if _start_worker():
            _logger.info("Subtitle update run started")
            return {"status": "started"}
        _logger.info("Subtitle update already running; ignoring start request")
        return {"status": "already_running"}

    with _lock:
        if not _running:
            _logger.info("Subtitle update not running; nothing to stop")
            return {"status": "already_stopped"}
        _stop_event.set()
    _logger.info("Stop requested for subtitle update run")
    return {"status": "stopping"}


@app.get("/update-subtitles")
def update_subtitles_status() -> dict:
    """Report whether a subtitle run is in progress and the last run's stats."""
    with _lock:
        running = _running
    _logger.debug("/update-subtitles status queried: running=%s", running)
    return {"running": running, "last_result": _last_result}
