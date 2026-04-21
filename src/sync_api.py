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


def _run_sync_loop() -> None:
    global _running, _config
    logger = _config.get_logger(__name__)

    try:
        config = Configuration()
        logger.info("Sync service started")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        sync_service = TorrentSyncService(config=config)

        async def _guarded_run() -> None:
            _stop_event.clear()
            poll_task = asyncio.create_task(sync_service.run())

            async def _wait_for_stop() -> None:
                await asyncio.get_event_loop().run_in_executor(None, _stop_event.wait)

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
    global _running, _task_thread, _config

    with _lock:
        if enabled:
            if _running:
                return {"status": "already_running"}
            _running = True
            _stop_event.clear()
            _task_thread = threading.Thread(target=_run_sync_loop, daemon=True)
            _task_thread.start()
            return {"status": "started"}
        else:
            if not _running:
                return {"status": "already_stopped"}
            _stop_event.set()
            _running = False
            return {"status": "stopping"}