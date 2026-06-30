# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## 1. Project Overview

`jellyfin-media-server-app` is a **media sync server** that sits next to a [Jellyfin](https://jellyfin.org/) instance and a [qBittorrent](https://www.qbittorrent.org/) client. It turns a private Hungarian tracker (**ncore.pro**) into an on-demand media library:

1. **Scrapes** ncore.pro for every Hungarian HD and SD movie and TV show.
2. **Stores** the torrent metadata (and derived movies / shows / seasons / local-file info) in a local **SQLite** database.
3. **Generates symlinks** that point to small placeholder `.mp4` files. Jellyfin sees a fully populated library *before any real bytes have been downloaded*.
4. When a user **presses play in Jellyfin**, the sync service detects it, downloads the corresponding torrent through qBittorrent (with a priority-based throttling scheme), then **rewrites the symlink** to point at the freshly downloaded real file and asks Jellyfin to refresh the item.

The result: Jellyfin always shows the entire ncore.pro catalogue, but disk space is only consumed for content that is actually watched.

## 2. Repository Layout

```
src/
  run.py                  # Entrypoint: launches both FastAPI apps in parallel processes
  config.py               # Env-var configuration + repository singletons
  parsing_api.py          # FastAPI app on :8800 — scraping & file-generation pipeline
  sync_api.py             # FastAPI app on :8801 — Jellyfin/qBittorrent sync loop
  sync.py                 # TorrentSyncService: priority-based download orchestrator
  ncore_scraper/          # Selenium-based ncore.pro scraper (Firefox + geckodriver)
  data_processing/
    data_processing.py    # Deduplicates torrents → Movies / ShowSeasons
    file_processing.py    # Downloads .torrent files, builds placeholder symlinks
    utils/                # Filename parsing helpers (S/E extraction, etc.)
  database/
    db.py                 # SQLModel engine + generic & per-model repositories
  models/                 # SQLModel tables: Torrent, Movie, Show, ShowSeason, LocalFileInformation
  jellyfin_api/
    jellyfin_api.py       # Jellyfin REST client (sessions, refresh)
    bittorrentapi.py      # Async qBittorrent wrapper (add, file priorities, speed limits)
test/                     # pytest unit tests
notebooks/                # Exploratory Jupyter notebooks (Jellyfin / TMDB API)
docker-compose.yaml       # media-server-app + jellyfin services
Dockerfile                # python:3.12-slim + Firefox ESR + geckodriver
create_env.sh             # Helper to scaffold a `.env` file
requirements.txt
```

## 3. Architecture

The application runs as a single container exposing **two FastAPI services** started by `src/run.py` via `multiprocessing`:

| Port | App                | Responsibility                                                                 |
|------|--------------------|--------------------------------------------------------------------------------|
| 8800 | `parsing_api`      | One-shot, long-running pipeline (12–48 h) that builds the catalogue            |
| 8801 | `sync_api`         | Long-lived poller that reacts to Jellyfin playback events                      |

They are split because the parsing pipeline blocks for many hours and must not stall the sync loop.

### 3.1 Parsing pipeline (`POST /parsing?pages=N`)

Located in `parsing_api.py` → `Scraper` → `DataProcessing` → `FileProcessing`.

1. **`Scraper.get_all_torrents`** — Selenium / Firefox logs in to ncore.pro and walks paginated browse pages for the four buckets: `(movie|show) × (HD|SD)`. Raw rows are persisted in the `torrent` table (`models/torrent.py`).
2. **`DataProcessing.process`** — Deduplicates torrents per IMDb ID:
   - **Movies**: keep the highest-quality torrent per IMDb link, write a `Movie` row.
   - **Shows**: pick one torrent per season, preferring single-season packs over multi-season packs, then by quality (`SD < HD < UHD`, never `UNASSIGNED` if avoidable), and write `Show` + `ShowSeason` rows.
3. **`FileProcessing.process`** — Two stages:
   - `__download_torrent_files` downloads each `.torrent` file via an authenticated `httpx` client into `TORRENT_FILES_LOCATION`, opens it with `torrentool`, and writes a `LocalFileInformation` row containing:
     - `torrent_file_local_path` — where the `.torrent` lives on disk
     - `main_media_files_local_path` — for shows: every file in the torrent joined by `;`; for movies: just the largest file
   - `__generate_symlink_to_placeholders` queries TMDB (rate-limited to 40 req/s) for proper titles, builds the Jellyfin-friendly directory tree under `VOLUME_MOVIE_DIR` / `VOLUME_SERIES_DIR`, and creates symlinks that point at one of the **placeholder `.mp4` files** in `VOLUME_PLACEHOLDER_TARGET_DIR`. The chosen placeholder communicates the expected wait time (`jellyfin-placeholder-1-hour-left.mp4`, `…-half-hour-left.mp4`, etc.). Each symlink path is stored in `LocalFileInformation.symlink_path` (semicolon-joined for shows, in the **same order** as `original_file_path` / `main_media_files_local_path`).

After this pipeline the on-disk library looks like a complete Jellyfin library, but every media file is a symlink to a placeholder.

### 3.2 Sync loop (`POST /sync?enabled=true`)

`TorrentSyncService` (`src/sync.py`) runs in a worker thread with its own asyncio loop and two cooperating tasks:

- **`_poll_jellyfin`** — every second calls `JellyfinApi.fetch_items` (active sessions). For each `NowPlayingItem`, extracts the IMDb ID from the path (`[imdbid-tt1234567]`), looks up the matching `Torrent` + `LocalFileInformation` + `ShowSeason`, computes which file inside the torrent corresponds to the played path (`_find_episode_index` matches against the `;`-split `symlink_path`), and pushes an `EpisodeRequest` onto an `asyncio.Queue`. If a show download is already in progress, an `_interrupt_event` is set to preempt it.
- **`_download_orchestrator`** — drains the queue and dispatches to either `_handle_movie_download` or the 3-phase `_handle_show_download`.

#### Show download — 3-phase priority scheme

For shows, the orchestrator calls `BittorrentAPI` to add the `.torrent` to qBittorrent and then runs three phases against the same torrent hash. Speed limits live in `bittorrentapi.py`:

| Phase | Scope                                  | Speed                  | qBittorrent file priority           |
|-------|----------------------------------------|------------------------|-------------------------------------|
| 1     | The exact episode the user clicked     | `SPEED_UNLIMITED` (0)  | All files = 0 (skip), target = 7    |
| 2     | The rest of the season torrent         | `SPEED_20_MBPS`        | All files = 1 (normal)              |
| 3     | Every other season of the same show    | `SPEED_5_MBPS`         | All files = 1, iterated per season  |

Any phase aborts cleanly when `_interrupt_event` fires (a newer episode was requested). `wait_for_files_complete` / `wait_for_torrent_complete` poll qBittorrent every `POLL_INTERVAL` (3 s) and update placeholder symlinks (e.g. swap `…-1-hour-left` for `…-half-hour-left`) as the ETA shrinks.

After each phase that completes, symlinks are rewritten and `JellyfinApi.refresh_item` is called so Jellyfin re-indexes the new file size.

### 3.3 Symlink lifecycle (the core trick)

```
Jellyfin library entry  ─┐
   (symlink on disk)     ├─►  while waiting:    placeholder .mp4 in VOLUME_PLACEHOLDER_TARGET_DIR
                         └─►  after download:   real file under VOLUME_DOWNLOADED_TARGET_DIR
```

Path bookkeeping per torrent (in `LocalFileInformation`):

- `original_file_path` — file path **inside the torrent** (semicolon-joined for multi-file/show torrents).
- `main_media_files_local_path` — selected media file(s) for symlinking (largest file for movies, all files for shows).
- `symlink_path` — absolute symlink path under `VOLUME_MOVIE_DIR` or `VOLUME_SERIES_DIR/<Show>/Season N/…`.
- `torrent_file_local_path` — path of the `.torrent` file under `TORRENT_FILES_LOCATION`.

Indices into the three semicolon-lists are aligned: `episode_file_index` from the played path is reused for `original_file_path[i]` and `symlink_path[i]`.

`_update_symlinks` / `_update_single_symlink` (`src/sync.py`) replace the placeholder target with `Path(save_path) / original_file`. They translate qBittorrent's `save_path` from the daemon's view (`VOLUME_DOWNLOADED_DIR`) to the container's view (`VOLUME_DOWNLOADED_TARGET_DIR`) before relinking.

## 4. Data model (SQLite via SQLModel)

| Table                  | Purpose                                                              |
|------------------------|----------------------------------------------------------------------|
| `torrent`              | Raw scraped torrent rows (uniquely keyed by `torrent_id` from ncore) |
| `movie`                | One per IMDb ID after dedup, FK → best `torrent.id`                  |
| `show`                 | One per series (by IMDb ID)                                          |
| `showseason`           | One per (show, season range), FK → chosen `torrent.id` for that season |
| `localfileinformation` | Per-torrent file/symlink bookkeeping (FK → `torrent.id`, unique)     |

All access goes through repositories in `src/database/db.py` (`BaseRepository` + `TorrentRepository`, `MovieRepository`, `ShowRepository`, `ShowSeasonsRepository`, `LocalFilesRepository`). Sessions are short-lived (`get_session` context manager) and instances are `expunge`d before being returned, so callers receive detached objects safe to pass between threads/loops.

The DB file is `database.db` at the repo / container root; it is bind-mounted via `VOLUME_DB_PATH` in `docker-compose.yaml`.

## 5. Configuration

All configuration is environment-driven (read in `src/config.py`). The `Configuration` class fails fast at import time if any required variable is missing. Helpful when scaffolding a local env: `./create_env.sh`.

Required env vars:

- **ncore.pro**: `NCORE_USERNAME`, `NCORE_PASSWORD`
- **Jellyfin**: `JELLYFIN_URL`, `JELLYFIN_USER_ID`, `JELLYFIN_API_KEY`
- **TMDB**: `TMDB_API_KEY` (used to resolve nice show names)
- **qBittorrent**: `QBITTORRENT_HOST`, `QBITTORRENT_PORT`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`
- **Filesystem layout** — see `docker-compose.yaml`. Each pair has a `…_DIR` (host side / qBittorrent side) and a `…_TARGET_DIR` (container side); `_update_symlinks` translates between them:
  - `VOLUME_MOVIE_DIR` / `VOLUME_MOVIE_TARGET_DIR`
  - `VOLUME_SERIES_DIR` / `VOLUME_SERIES_TARGET_DIR`
  - `VOLUME_DOWNLOADED_DIR` / `VOLUME_DOWNLOADED_TARGET_DIR`
  - `VOLUME_PLACEHOLDER_DIR` / `VOLUME_PLACEHOLDER_TARGET_DIR` (read-only mount)
  - `TORRENT_FILES_LOCATION` / `TORRENT_FILES_TARGET_LOCATION`
  - `VOLUME_DB_PATH` (bind-mounted onto `/app/database.db`)
  - `VOLUME_RUN_LOG_PATH` (bind-mounted onto `/app/run.log`)

The placeholder directory must contain these files (referenced as `placeholder_*_path` attributes on `Configuration`):

- `jellyfin-placeholder.mp4`
- `jellyfin-placeholder-1-hour-left.mp4`
- `jellyfin-placeholder-less-then-1-hour-left.mp4`
- `jellyfin-placeholder-half-hour-left.mp4`
- `jellyfin-placeholder-less-then-20-minutes-left.mp4`
- `jellyfin-placeholder-less-then-10-minutes-left.mp4`
- `jellyfin-placeholder-less-then-5-minutes-left.mp4`
- `jellyfin-placeholder-less-then-a-few-minutes-left.mp4`

## 6. Running locally

```bash
# 1. Create a virtualenv and install deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Populate the env (see section 5 / create_env.sh) and export it
set -a && source .env && set +a

# 3. Initialise DB + run both APIs
cd src
python run.py
```

For the Selenium scraper you need Firefox + geckodriver on `PATH` (the Dockerfile installs Firefox ESR and geckodriver 0.36.0).

### Docker

```bash
docker compose up -d
```

The compose file also brings up Jellyfin. qBittorrent is **not** included — point `QBITTORRENT_HOST/PORT` at an existing instance that has access to `VOLUME_DOWNLOADED_DIR`.

### Triggering pipelines

```bash
# Scrape N pages of each (movie|show)×(HD|SD) bucket and build placeholders
curl -X POST 'http://localhost:8800/parsing?pages=50'

# Re-run only the dedup + file/symlink step
curl -X POST 'http://localhost:8800/processing'

# Start / stop the Jellyfin → qBittorrent sync loop
curl -X POST 'http://localhost:8801/sync?enabled=true'
curl -X POST 'http://localhost:8801/sync?enabled=false'
```

## 7. Testing

```bash
pytest test/
```

`test/test_scraper.py` exercises ncore parsing fixtures (the scraper accepts `for_test=True` to skip launching a real WebDriver). `test/test_series.py` covers show/season selection logic.

When adding tests, prefer constructing `Scraper(..., for_test=True)` and feeding HTML fixtures, rather than touching the real ncore site.

## 8. Conventions for agents editing this repo

- **Python 3.12**, type hints throughout. Keep them when editing.
- **Configuration access** goes through `Configuration` and its repository attributes — do not instantiate engines or repositories ad-hoc.
- **Database access** goes through the repositories in `src/database/db.py`. Add new query methods there rather than opening sessions inline.
- **Async vs sync**: `sync_api` / `sync.py` / `bittorrentapi.py` are async; blocking calls (Jellyfin REST, DB) are dispatched via `loop.run_in_executor`. Preserve this pattern.
- **Path semantics**: never compare/concat paths from the qBittorrent daemon and the container directly. Always go through the `downloaded_directory → downloaded_target_directory` translation as in `_update_symlinks`.
- **Symlink invariant**: `original_file_path`, `main_media_files_local_path` and `symlink_path` are `;`-joined and **index-aligned**. If you change how one is built, change the others in lockstep.
- **Logging**: use `self.logger = config.get_logger(__name__)`. The root logger writes to both `run.log` and stdout; do not reconfigure it.
- **Selenium selectors** live in `src/ncore_scraper/selectors.py`. Update them there, not inline in `scraper.py`.
- **Long-running endpoints** in `parsing_api.py` are intentionally blocking — they are designed to be fired once and observed via logs. Don't add background-task plumbing without a clear reason.
- Avoid introducing new top-level dependencies without updating `requirements.txt` and the `Dockerfile`.

## 9. Known caveats

- The parsing pipeline can take 12–48 hours end-to-end; design changes to it should remain idempotent (everything is `save_if_new` / `os.path.exists` guarded).
- ncore.pro frequently changes its DOM; scraper failures usually mean updating `selectors.py`.
- TMDB is rate-limited to 40 req/s — `file_processing.py` sleeps 25 ms between show lookups. Don't remove that.
- `_default_engine` is a process-global SQLite engine with `check_same_thread=False`. Tables must be created (`init_db`) **before** `multiprocessing.Process` forks — `run.py` already does this.
