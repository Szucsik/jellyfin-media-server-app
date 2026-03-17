from typing import Optional

import requests

from config import Configuration


class JellyfinApi:
    """Client for querying the Jellyfin API for movies and shows with play status."""

    def __init__(self, config: Configuration):
        self.logger = config.logger

        self.server_url = config.jellyfin_url.rstrip("/")
        self.api_key = config.jellyfin_api_key
        self.user_id = config.jellyfin_user_id

        self.state: dict[str, int] = {}
        self.first_run = True

        if not self.api_key:
            raise ValueError("JELLYFIN_API_KEY environment variable is not set")
        if not self.user_id:
            raise ValueError("JELLYFIN_USER_ID environment variable is not set")

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
            # "Limit": 5000,
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

    # ── Core polling ────────────────────────────────────────────────────────────
    def poll_once(self) -> list[dict]:
        """
        Fetch items, diff against *state*, and return newly-played items.

        Updates *state* in place and persists it to disk.
        Returns an empty list on the first run (baseline capture).
        """
        items = self.fetch_items(["Movie", "Series", "Episode"])

        if not items:
            self.logger.warning("No items returned – check credentials/URL.")
            return []

        newly_played: list[dict] = []

        for item in items:
            item_id = item.get("Id", "")
            count = self.play_count(item)

            prev = self.state.get(item_id)
            if prev is not None and count > prev and not self.first_run:
                newly_played.append(item)

            self.state[item_id] = count

        if self.first_run:
            self.first_run = False

        return newly_played