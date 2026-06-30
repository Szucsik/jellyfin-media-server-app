# jellyfin-media-server-app

> Make your entire ncore.pro library appear inside Jellyfin — and only download what you actually press play on.

`jellyfin-media-server-app` is a small media-sync service that bridges three things:

- **[ncore.pro](https://ncore.pro)** — a private Hungarian torrent tracker (movies + TV shows, HD & SD).
- **[Jellyfin](https://jellyfin.org/)** — your media server.
- **[qBittorrent](https://www.qbittorrent.org/)** — the torrent client that actually does the downloading.

It scrapes the whole ncore catalogue, builds a fully populated Jellyfin library out of *symlinks to placeholder `.mp4` files*, and then — the moment you click play in Jellyfin — it starts downloading the matching torrent and rewrites the symlink to point at the real file.

The result: Jellyfin looks like it has terabytes of content, but your disk only fills up with what someone watches.

---

## ✨ How it works

```
                     ┌──────────────────────┐
                     │    ncore.pro          │  (Selenium scraper)
                     └──────────┬────────────┘
                                │  torrents (HD/SD movies & shows)
                                ▼
                     ┌──────────────────────┐
                     │   SQLite database    │  torrents · movies · shows
                     │   (sqlmodel)         │  show_seasons · local_files
                     └──────────┬───────────┘
                                │  build directory tree
                                ▼
   /media/movies/Foo (2021)/Foo.mkv  ──►  symlink  ──►  placeholder.mp4
   /media/series/Bar/Season 1/S01E01.mkv ─► symlink ─►  placeholder-1-hour-left.mp4
                                │
                                │  Jellyfin scans, shows full library
                                ▼
                     ┌──────────────────────┐
                     │      Jellyfin        │
                     └──────────┬───────────┘
                                │  user presses ▶
                                ▼
                     ┌──────────────────────┐
                     │  TorrentSyncService  │  ─►  qBittorrent  ─►  real file
                     └──────────┬───────────┘
                                │  rewrite symlink, refresh Jellyfin
                                ▼
   /media/series/Bar/Season 1/S01E01.mkv  ──►  symlink  ──►  /downloads/.../S01E01.mkv
```

### Two HTTP services in one container

| Port | Service       | What it does                                                                |
|------|---------------|------------------------------------------------------------------------------|
| 8800 | Parsing API   | One-shot, **long-running** (12–48 h) pipeline that builds the catalogue.    |
| 8801 | Sync API      | Long-lived poller that watches Jellyfin and triggers downloads on play.     |

They run in parallel processes (see [src/run.py](src/run.py)) because the parsing pipeline is too slow to share a loop with the sync poller.

### Smart download throttling for TV shows

When you press play on an episode of a multi-episode torrent, the sync service runs **three phases** against the same `.torrent`:

| Phase | What gets downloaded                       | Speed limit          |
|-------|--------------------------------------------|----------------------|
| 1     | Just the episode you clicked               | ⚡ Unlimited          |
| 2     | The rest of that season                    | 🚗 20 Mbit/s         |
| 3     | Every other season of the same show        | 🐢 5 Mbit/s          |

If you start playing a *different* episode mid-download, the in-progress phase is interrupted and the new episode jumps straight back to phase 1 at full speed.

### Placeholders that tell you how long to wait

While a download is running, the symlink keeps pointing at a placeholder `.mp4`, but the placeholder is swapped as the ETA shrinks:

```
jellyfin-placeholder-1-hour-left.mp4
jellyfin-placeholder-half-hour-left.mp4
jellyfin-placeholder-less-then-20-minutes-left.mp4
jellyfin-placeholder-less-then-10-minutes-left.mp4
…
```

So the user opening Jellyfin sees a video that literally tells them roughly how long they have to wait. Once the file is done, the symlink flips to the real file and Jellyfin is asked to refresh the item.

---

## 🚀 Quick start (Docker)

1. **Clone** this repo and run `./create_env.sh` to scaffold a `.env` file.
2. **Fill in** the `.env` with credentials for ncore.pro, Jellyfin, qBittorrent and TMDB, plus the host/container paths for your media volumes.
3. Make sure the **placeholder directory** (`VOLUME_PLACEHOLDER_DIR`) contains all the `jellyfin-placeholder*.mp4` files listed in [AGENTS.md §5](AGENTS.md).
4. Bring everything up:

   ```bash
   docker compose up -d
   ```

   This launches `media-server-app` and a `jellyfin` container side by side. **qBittorrent is not included** — point `QBITTORRENT_HOST/PORT` at an existing instance that has access to your downloads volume.

5. Trigger the catalogue build (this takes hours — fire and forget, watch `run.log`):

   ```bash
   curl -X POST 'http://localhost:8800/parsing?pages=50'
   ```

6. Start the play-to-download sync loop:

   ```bash
   curl -X POST 'http://localhost:8801/sync?enabled=true'
   ```

7. Open Jellyfin → press ▶ on something → watch it download. 🎬

To stop the sync loop:

```bash
curl -X POST 'http://localhost:8801/sync?enabled=false'
```

---

## 🛠️ Running from source

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Load your .env into the shell
set -a && source .env && set +a

cd src
python run.py
```

You'll need **Firefox + geckodriver** on your `PATH` for the Selenium scraper (the Dockerfile installs Firefox ESR + geckodriver 0.36.0 for you).

### HTTP endpoints

| Method | Endpoint                                | Purpose                                                           |
|--------|-----------------------------------------|-------------------------------------------------------------------|
| POST   | `http://localhost:8800/parsing?pages=N` | Scrape `N` pages of each (movie\|show)×(HD\|SD) bucket and build placeholders. |
| POST   | `http://localhost:8800/processing`      | Re-run only the dedup + symlink stage (no scraping).              |
| POST   | `http://localhost:8800/download-torrent`| Re-download missing `.torrent` files for items already in the DB. |
| POST   | `http://localhost:8801/sync?enabled=true`  | Start the Jellyfin → qBittorrent sync loop.                    |
| POST   | `http://localhost:8801/sync?enabled=false` | Stop the sync loop.                                            |

---

## ⚙️ Configuration

Every setting is read from environment variables (see [src/config.py](src/config.py)). The service refuses to start if any required variable is missing.

| Group         | Variables                                                                                  |
|---------------|--------------------------------------------------------------------------------------------|
| ncore.pro     | `NCORE_USERNAME`, `NCORE_PASSWORD`                                                         |
| Jellyfin      | `JELLYFIN_URL`, `JELLYFIN_USER_ID`, `JELLYFIN_API_KEY`                                     |
| qBittorrent   | `QBITTORRENT_HOST`, `QBITTORRENT_PORT`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`     |
| TMDB          | `TMDB_API_KEY` (used to resolve nice show names)                                           |
| Filesystem    | `VOLUME_MOVIE_DIR` / `VOLUME_MOVIE_TARGET_DIR`, `VOLUME_SERIES_DIR` / `VOLUME_SERIES_TARGET_DIR`, `VOLUME_DOWNLOADED_DIR` / `VOLUME_DOWNLOADED_TARGET_DIR`, `VOLUME_PLACEHOLDER_DIR` / `VOLUME_PLACEHOLDER_TARGET_DIR`, `TORRENT_FILES_LOCATION` / `TORRENT_FILES_TARGET_LOCATION`, `VOLUME_DB_PATH`, `VOLUME_RUN_LOG_PATH` |

Each `…_DIR` / `…_TARGET_DIR` pair represents the **host (or qBittorrent) view** vs the **container view** of the same directory; the sync service automatically translates between them when rewriting symlinks.

---

## 🧪 Tests

```bash
pytest test/
```

The scraper takes a `for_test=True` flag so unit tests can feed it HTML fixtures instead of hitting the real ncore site.

---

## 📦 Project layout (short version)

```
src/
  run.py              # launches both FastAPI apps
  parsing_api.py      # :8800 — scrape + build catalogue
  sync_api.py         # :8801 — start/stop sync loop
  sync.py             # the play-to-download orchestrator
  ncore_scraper/      # Selenium scraper + selectors
  data_processing/    # dedup, .torrent download, symlink generation
  database/db.py      # SQLModel engine + repositories
  models/             # Torrent, Movie, Show, ShowSeason, LocalFileInformation
  jellyfin_api/       # Jellyfin REST + async qBittorrent wrapper
test/                 # pytest unit tests
```

For a deeper architectural tour (data model, semicolon-joined path invariants, conventions for contributors), see [AGENTS.md](AGENTS.md).

---

## ⚠️ Caveats

- The full **parsing pipeline takes 12–48 hours** end-to-end. It's idempotent — safe to re-run, it skips work that's already done.
- ncore.pro changes its DOM from time to time; if scraping breaks, update the selectors in [src/ncore_scraper/selectors.py](src/ncore_scraper/selectors.py).
- TMDB is rate-limited to **40 requests/second** — the file processor sleeps 25 ms between show lookups. Don't remove that.
- This software is intended for **personal use with content you are entitled to**. You are responsible for complying with the laws of your jurisdiction and the terms of any tracker you connect to.

---

## 📝 License

No license file is currently shipped with this repository. Treat the code as "all rights reserved" until a license is added.
