#!/usr/bin/env python3
"""Launch both FastAPI applications (parsing + sync) in a single process."""
import multiprocessing
import uvicorn 

from database.db import init_db


# We need two running async API's in parallel because 
# the update and parsing process lasts for 12-48 hours
def run_parsing_api() -> None:
    """Start Parsing API"""
    uvicorn.run("parsing_api:app", host="0.0.0.0", port=8800)


def run_sync_api() -> None:
    """Run Sync API"""
    uvicorn.run("sync_api:app", host="0.0.0.0", port=8801)


if __name__ == "__main__":
    init_db()

    parsing = multiprocessing.Process(target=run_parsing_api, daemon=True)
    sync = multiprocessing.Process(target=run_sync_api, daemon=True)

    parsing.start()
    sync.start()

    try:
        parsing.join()
        sync.join()
    except KeyboardInterrupt:
        parsing.terminate()
        sync.terminate()
