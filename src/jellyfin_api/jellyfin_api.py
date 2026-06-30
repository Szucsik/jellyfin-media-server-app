import requests

from config import Configuration


class JellyfinApi:
    """Client for querying the Jellyfin API for movies and shows with play status."""

    def __init__(self, config: Configuration):
        self.logger = config.logger

        self.server_url = config.jellyfin_url.rstrip("/")
        self.api_key = config.jellyfin_api_key
        self.user_id = config.jellyfin_user_id

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

    def fetch_items(self) -> list[dict]:
        """
        Fetch all items of the given types from Jellyfin.
        Returns a flat list of item dicts.
        """
        url = f"{self.server_url}/Sessions"

        try:
            resp = requests.get(url, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            self.logger.error("Failed to fetch items: %s", exc)
            return []

    def refresh_item(self, item_id: str) -> None:
        """
        Refresh target item
        """
        url = f"{self.server_url}/Items/{item_id}/Refresh"

        params = {
            "metadataRefreshMode": "FullRefresh",
            "imageRefreshMode": "Default",
            "replaceAllMetadata": "false",
            "replaceAllImages": "false",
        }

        try:
            self.logger.info('Post request to update the Jellyfin item %s', url)
            resp = requests.post(url, headers=self._headers(), params=params, timeout=30)
            self.logger.info('Post request completed')
            resp.raise_for_status()
            self.logger.info('Jellyfin refresh has been triggered.')
        except requests.RequestException as exc:
            self.logger.error("Failed to refresh item: %s Exception: %s", item_id, exc)
            return