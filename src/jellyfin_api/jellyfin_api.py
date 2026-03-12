import time
import os
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from config import Configuration


class TorrentSync:
    trigger_path: str
    imdbid: str = ""
    downloading: bool = False

class JellyfinApi:
    """Client for querying the Jellyfin API for movies and shows with play status."""

    def __init__(self, config: Configuration):
        self.DOWNLOAD_TORRENT: list[TorrentSync] = []

        self.poll_internal   = int(os.getenv("POLL_INTERVAL_SECONDS", "1"))
        self.log_file        = "jellyfin_monitor.log"
        self.logger = config.logger

        self.state_file = "state"

        self.server_url = config.jellyfin_url
        self.api_key = config.jellyfin_api_key
        self.user_id = config.jellyfin_user_id

        if not self.api_key:
            raise ValueError("JELLYFIN_API_KEY environment variable is not set")
        if not self.user_id:
            raise ValueError("JELLYFIN_USER_ID environment variable is not set")

        self.server_url = self.server_url.rstrip("/")

    # ── Jellyfin helpers ──────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        return {
            "X-Emby-Authorization": (
                f'MediaBrowser Client="JellyfinMonitor", '
                f'Device="PythonScript", DeviceId="monitor-001", Version="1.0", Token="{self.api_key}"'
            ),
            "Accept": "application/json",
        }


    def fetch_items(self, item_types: list[str]) -> list[dict]:
        """
        Fetch all items of the given types from Jellyfin.
        Returns a flat list of item dicts.
        """
        types_param = ",".join(item_types)

        # Build URL – use /Users/{id}/Items if a user ID is configured
        if self.user_id:
            url = f"{self.server_url}/Users/{self.user_id}/Items"
        else:
            url = f"{self.server_url}/Items"

        params = {
            "IncludeItemTypes": types_param,
            "Recursive": "true",
            "Fields": "UserData,Id,Name,Type,ProductionYear,SeriesName,ParentIndexNumber,IndexNumber,MediaSources,Path",
            "Limit": 5000,
        }

        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data.get("Items", [])
        except requests.RequestException as exc:
            self.logger.error("Failed to fetch items: %s", exc)
            return []


    def play_count(self, item: dict) -> int:
        """Extract play count from item, handling both UserData shapes."""
        user_data = item.get("UserData") or {}
        return int(user_data.get("PlayCount", 0))


    def item_label(self, item: dict) -> str:
        """Human-readable label for an item."""
        name  = item.get("Name", "Unknown")
        itype = item.get("Type", "")
        year  = item.get("ProductionYear", "")

        if itype == "Episode":
            series  = item.get("SeriesName", "?")
            season  = item.get("ParentIndexNumber", "?")
            episode = item.get("IndexNumber", "?")
            return f"{series} S{season:02d}E{episode:02d} – {name}"

        return f"{name} ({year})" if year else name

    # ── State helpers ─────────────────────────────────────────────────────────────
    def load_state(self) -> dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}


    def save_state(self, state: dict) -> None:
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)


    # ── Core loop ─────────────────────────────────────────────────────────────────
    def run_loop(self) -> None:
        self.logger.info("=" * 60)
        self.logger.info("Jellyfin Monitor starting")
        self.logger.info("  Server : %s", self.server_url)
        self.logger.info("  Interval: %ds", self.poll_internal)
        self.logger.info("=" * 60)

        if not self.api_key:
            self.logger.error("JELLYFIN_API_KEY is not set. Edit .env and restart.")
            return

        # Load persisted play counts from previous run
        state: dict[str, int] = self.load_state()   # { item_id: play_count }
        first_run = not bool(state)

        while True:
            self.logger.info("Polling Jellyfin…")
            items = self.fetch_items(["Movie", "Series", "Episode"])

            if not items:
                self.logger.warning("No items returned – check credentials/URL.")
                time.sleep(self.poll_internal)
                continue

            unplayed: list[dict] = []
            newly_played: list[dict] = []

            for item in items:
                item_id = item.get("Id", "")
                count   = self.play_count(item)

                if count == 0:
                    unplayed.append(item)

                prev = state.get(item_id)
                if prev is not None and prev == 0 and count >= 1:
                    newly_played.append(item)

                # Update state
                state[item_id] = count

            self.save_state(state)

            # ── Report unplayed ───────────────────────────────────────────────────
            movies   = [i for i in unplayed if i.get("Type") == "Movie"]
            episodes = [i for i in unplayed if i.get("Type") == "Episode"]
            series   = [i for i in unplayed if i.get("Type") == "Series"]

            self.logger.info(
                "Unplayed — Movies: %d | Series: %d | Episodes: %d",
                len(movies), len(series), len(episodes),
            )

            # ── Report newly played ───────────────────────────────────────────────
            if newly_played and not first_run:
                self.logger.info("🎬 %d item(s) played for the first time this cycle:", len(newly_played))
                for item in newly_played:
                    self.DOWNLOAD_TORRENT.append(TorrentSync(trigger_path=item.get("Path", None)))

            elif first_run:
                self.logger.info("First run – baseline captured (%d items tracked).", len(state))
                first_run = False

            self.logger.info("Next poll in %ds…\n", self.poll_internal)
            time.sleep(self.poll_internal)

    def sync_torrents(self) -> None:
        """a"""
        while(True):
            if len(self.DOWNLOAD_TORRENT) > 0:
                