#!/usr/bin/env python3
"""Launch both FastAPI applications (parsing + sync) in a single process."""

import uvicorn
import time
import multiprocessing


def run_parsing_api() -> None:
    uvicorn.run("parsing_api:app", host="0.0.0.0", port=8800)


def run_sync_api() -> None:
    uvicorn.run("sync_api:app", host="0.0.0.0", port=8801)


if __name__ == "__main__":
    parsing = multiprocessing.Process(target=run_parsing_api, daemon=True)
    time.sleep(10)  # TODO: Sleep before the sync process to prevent db creating bug
    sync = multiprocessing.Process(target=run_sync_api, daemon=True)

    parsing.start()
    sync.start()

    try:
        parsing.join()
        sync.join()
    except KeyboardInterrupt:
        parsing.terminate()
        sync.terminate()
