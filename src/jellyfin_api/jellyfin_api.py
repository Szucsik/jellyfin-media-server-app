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

    # ── Library queries ───────────────────────────────────────────────────────
    def fetch_library_items(
        self,
        item_types: str,
        fields: str = "ProviderIds,Path,MediaStreams",
        page_size: int = 200,
    ) -> list[dict]:
        """Fetch every library item of the given comma-separated types.

        Pages through the results and returns a flat list of item dicts. Used to
        map database records (by IMDb id) to Jellyfin item ids.
        """
        base_path = f"/Users/{self.user_id}/Items" if self.user_id else "/Items"
        url = f"{self.server_url}{base_path}"

        items: list[dict] = []
        start_index = 0

        self.logger.info("Fetching library items of type(s) '%s' from %s", item_types, url)

        while True:
            params = {
                "IncludeItemTypes": item_types,
                "Recursive": "true",
                "Fields": fields,
                "StartIndex": start_index,
                "Limit": page_size,
                "SortBy": "SortName",
            }
            try:
                resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                self.logger.error("Failed to fetch library items (%s): %s", item_types, exc)
                break

            batch = data.get("Items", [])
            items.extend(batch)

            total = data.get("TotalRecordCount", len(items))
            self.logger.debug(
                "Fetched %d item(s) of '%s' at start_index=%d (total=%d)",
                len(batch), item_types, start_index, total,
            )
            start_index += page_size
            if not batch or start_index >= total:
                break

        self.logger.info("Fetched %d '%s' item(s) in total", len(items), item_types)
        return items

    def fetch_series_episodes(
        self,
        series_id: str,
        fields: str = "ProviderIds,Path,MediaStreams,ParentIndexNumber,IndexNumber",
    ) -> list[dict]:
        """Fetch every episode of a series, including season/episode numbers."""
        url = f"{self.server_url}/Shows/{series_id}/Episodes"
        params = {"userId": self.user_id, "Fields": fields}

        self.logger.debug("Fetching episodes for series %s", series_id)
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
            resp.raise_for_status()
            episodes = resp.json().get("Items", [])
            self.logger.debug("Series %s returned %d episode(s)", series_id, len(episodes))
            return episodes
        except requests.RequestException as exc:
            self.logger.error("Failed to fetch episodes for series %s: %s", series_id, exc)
            return []

    # ── Subtitles (Open Subtitles plugin) ─────────────────────────────────────
    @staticmethod
    def item_has_subtitle_language(item: dict, language: str) -> bool:
        """True if the item already exposes a subtitle stream in the given language."""
        language = language.lower()
        for stream in item.get("MediaStreams", []) or []:
            if stream.get("Type") != "Subtitle":
                continue
            stream_lang = (stream.get("Language") or "").lower()
            if stream_lang == language:
                return True
        return False

    def search_remote_subtitles(self, item_id: str, language: str) -> list[dict]:
        """Search remote providers (Open Subtitles) for subtitles in a language.

        Returns the list of RemoteSubtitleInfo dicts (each has an ``Id`` usable
        with :meth:`download_remote_subtitle`).
        """
        url = f"{self.server_url}/Items/{item_id}/RemoteSearch/Subtitles/{language}"

        self.logger.debug("Searching remote %s subtitles for item %s at %s", language, item_id, url)
        try:
            resp = requests.get(url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            results = resp.json()
            self.logger.debug("Remote subtitle search for item %s returned %d result(s)", item_id, len(results))
            return results
        except requests.RequestException as exc:
            self.logger.error("Subtitle search failed for item %s: %s", item_id, exc)
            return []

    def download_remote_subtitle(self, item_id: str, subtitle_id: str) -> bool:
        """Download and attach a remote subtitle to an item. Returns True on success."""
        url = f"{self.server_url}/Items/{item_id}/RemoteSearch/Subtitles/{subtitle_id}"

        self.logger.info("Downloading remote subtitle %s for item %s", subtitle_id, item_id)
        try:
            resp = requests.post(url, headers=self._headers(), timeout=60)
            resp.raise_for_status()
            self.logger.info("Remote subtitle %s attached to item %s", subtitle_id, item_id)
            return True
        except requests.RequestException as exc:
            self.logger.error(
                "Subtitle download failed for item %s (subtitle %s): %s",
                item_id, subtitle_id, exc,
            )
            return False
