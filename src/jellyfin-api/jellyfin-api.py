import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests


logger = logging.getLogger(__name__)


@dataclass
class MediaPlayInfo:
    name: str
    jellyfin_id: str
    played: bool
    play_count: int
    last_played_date: Optional[datetime]


class JellyfinApi:
    """Client for querying the Jellyfin API for movies and shows with play status."""

    def __init__(self):
        self.server_url = os.getenv("JELLYFIN_SERVER_URL", "http://localhost:8096")
        self.api_key = os.getenv("JELLYFIN_API_KEY")
        self.user_id = os.getenv("JELLYFIN_USER_ID")

        if not self.api_key:
            raise ValueError("JELLYFIN_API_KEY environment variable is not set")
        if not self.user_id:
            raise ValueError("JELLYFIN_USER_ID environment variable is not set")

        self.server_url = self.server_url.rstrip("/")

    def _get_headers(self) -> dict:
        return {"Authorization": f'MediaBrowser Token="{self.api_key}"'}

    def _get_items(self, item_type: str) -> list[MediaPlayInfo]:
        url = f"{self.server_url}/Users/{self.user_id}/Items"
        params = {
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "Fields": "DateLastMediaAdded",
        }

        response = requests.get(url, headers=self._get_headers(), params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        results = []

        for item in data.get("Items", []):
            user_data = item.get("UserData", {})
            played = user_data.get("Played", False)
            play_count = user_data.get("PlayCount", 0)

            last_played_raw = user_data.get("LastPlayedDate")
            last_played_date = None
            if last_played_raw:
                last_played_date = datetime.fromisoformat(last_played_raw.replace("Z", "+00:00"))

            results.append(MediaPlayInfo(
                name=item.get("Name", ""),
                jellyfin_id=item.get("Id", ""),
                played=played,
                play_count=play_count,
                last_played_date=last_played_date,
            ))

        logger.info("Fetched %d %s items from Jellyfin", len(results), item_type.lower())
        return results

    def get_movies(self) -> list[MediaPlayInfo]:
        """Get all movies with their play status and last viewed date."""
        return self._get_items("Movie")

    def get_shows(self) -> list[MediaPlayInfo]:
        """Get all shows with their play status and last viewed date."""
        return self._get_items("Series")
