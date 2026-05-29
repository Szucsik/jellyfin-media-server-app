import asyncio
import threading

from fastapi import FastAPI

from config import Configuration
from sync import TorrentSyncService

app = FastAPI(title="Jellyfin & BitTorrent Sync API")

_lock = threading.Lock()
_running = False
_task_thread: threading.Thread | None = None
_stop_event = threading.Event()
_config = Configuration()
_logger = _config.get_logger(__name__)

AUTO_START_DELAY_SECONDS = 30


def _start_sync_thread() -> bool:
    """Start the sync worker thread. Returns True if started, False if already running."""
    global _running, _task_thread
    with _lock:
        if _running:
            return False
        _running = True
        _stop_event.clear()
        _task_thread = threading.Thread(target=_run_sync_loop, daemon=True)
        _task_thread.start()
        return True


def _run_sync_loop() -> None:
    global _running
    logger = _logger

    try:
        logger.info("Sync service started")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        sync_service = TorrentSyncService(config=_config)

        async def _guarded_run() -> None:
            _stop_event.clear()
            poll_task = asyncio.create_task(sync_service.run())

            async def _wait_for_stop() -> None:
                await asyncio.get_running_loop().run_in_executor(None, _stop_event.wait)

            stop_task = asyncio.create_task(_wait_for_stop())

            done, pending = await asyncio.wait(
                {poll_task, stop_task}, return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

        loop.run_until_complete(_guarded_run())
        logger.info("Sync service stopped")
    except Exception as exc:
        logger.error("Sync service error: %s", exc)
    finally:
        with _lock:
            _running = False


@app.post("/sync")
def toggle_sync(enabled: bool) -> dict:
    """Start or stop the Jellyfin & BitTorrent sync loop."""
    global _running

    with _lock:
        currently_running = _running

    if enabled:
        if currently_running:
            return {"status": "already_running"}
        if _start_sync_thread():
            return {"status": "started"}
        return {"status": "already_running"}

    with _lock:
        if not _running:
            return {"status": "already_stopped"}
        _stop_event.set()
        _running = False
    return {"status": "stopping"}


@app.on_event("startup")
def _auto_start_sync() -> None:
    """Automatically start the sync loop shortly after the app boots."""
    def _delayed_start() -> None:
        _stop_event.wait(AUTO_START_DELAY_SECONDS)
        if _stop_event.is_set():
            return
        if _start_sync_thread():
            _logger.info("Sync loop auto-started after %ds", AUTO_START_DELAY_SECONDS)
        else:
            _logger.info("Sync loop auto-start skipped: already running")

    threading.Thread(target=_delayed_start, daemon=True).start()