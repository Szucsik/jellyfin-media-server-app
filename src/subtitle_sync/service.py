from typing import Optional

from config import Configuration
from jellyfin_api.jellyfin_api import JellyfinApi


class SubtitleSyncService:
    """Downloads Hungarian subtitles for a single Jellyfin item.

    Subtitles are fetched through Jellyfin's built-in remote subtitle search
    (the OpenSubtitles plugin configured on the server), so no extra API key is
    needed here — the existing Jellyfin credentials are used.
    """

    LANGUAGE = "hu"

    def __init__(self, config: Configuration, jellyfin: Optional[JellyfinApi] = None) -> None:
        self.config = config
        self.logger = config.get_logger(__name__)
        self.jellyfin = jellyfin or JellyfinApi(config)

    def download_for_item(self, item_id: str) -> str:
        """Ensure a Jellyfin movie / episode item has a Hungarian subtitle.

        Returns one of: ``already_present``, ``not_found``, ``downloaded``,
        ``failed``. Never raises — callers can trigger it without guarding.
        """
        if not item_id:
            return "failed"

        item = self.jellyfin.get_item(item_id)
        if item is None:
            return "failed"

        if self.jellyfin.item_has_subtitle_language(item, self.LANGUAGE):
            self.logger.info("Item %s already has a Hungarian subtitle", item_id)
            return "already_present"

        candidates = self.jellyfin.search_remote_subtitles(item_id, self.LANGUAGE)
        if not candidates:
            self.logger.info("No Hungarian subtitle found for item %s", item_id)
            return "not_found"

        subtitle_id = candidates[0].get("Id")
        if not subtitle_id:
            return "not_found"

        if self.jellyfin.download_remote_subtitle(item_id, subtitle_id):
            self.logger.info("Hungarian subtitle %s downloaded for item %s", subtitle_id, item_id)
            return "downloaded"

        return "failed"
