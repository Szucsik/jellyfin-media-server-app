#!/usr/bin/env python3

from config import SoPConfig

import csv
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ==========================
# Configuration
# ==========================

JELLYFIN_URL = SoPConfig.JELLYFIN_URL
API_KEY = SoPConfig.JELLYFIN_API_KEY

PAGE_SIZE = 500
OUTPUT_CSV = "jellyfin_missing_hungarian_subtitles.csv"

PLACEHOLDER_PATH = "/placeholders/jellyfin-placeholder.mp4"

HEADERS = {
    "X-Emby-Token": API_KEY,
    "Accept": "application/json",
}


# =====================================================

session = requests.Session()

retries = Retry(
    total=5,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)

session.mount(
    "http://",
    HTTPAdapter(max_retries=retries)
)

session.mount(
    "https://",
    HTTPAdapter(max_retries=retries)
)


def has_real_media_source(item):
    """
    Skip Jellyfin placeholder files
    """

    for source in item.get("MediaSources", []):

        path = (
            source.get("Path")
            or ""
        ).lower()

        if path != PLACEHOLDER_PATH.lower():
            return True

    return False



def has_hungarian_subtitle(item):
    """
    Returns True if the item has HU subtitles
    """

    for stream in item.get("MediaStreams", []):

        if stream.get("Type") != "Subtitle":
            continue

        language = (
            stream.get("Language")
            or ""
        ).lower()

        if language in (
            "hu",
            "hun",
        ):
            return True

    return False



# =====================================================

start = 0
processed = 0
missing_hu = 0


with open(
    OUTPUT_CSV,
    "w",
    newline="",
    encoding="utf-8"
) as csvfile:

    writer = csv.DictWriter(
        csvfile,
        fieldnames=[
            "type",
            "name",
            "series",
            "season",
            "episode",
            "year",
            "path",
            "id",
        ],
    )

    writer.writeheader()


    while True:

        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Episode",
            "Fields": (
                "MediaSources,"
                "MediaStreams,"
                "SeriesName,"
                "ParentIndexNumber,"
                "IndexNumber,"
                "ProductionYear,"
                "Path"
            ),
            "Limit": PAGE_SIZE,
            "StartIndex": start,
        }


        print(
            f"Fetching "
            f"{start:,} - {start + PAGE_SIZE - 1:,}"
        )


        response = session.get(
            f"{JELLYFIN_URL}/Items",
            headers=HEADERS,
            params=params,
            timeout=(10,300),
        )

        response.raise_for_status()

        items = response.json().get(
            "Items",
            []
        )


        if not items:
            break


        for item in items:

            # Remove placeholder entries
            if not has_real_media_source(item):
                continue


            # Has Hungarian subtitles -> skip
            if has_hungarian_subtitle(item):
                continue


            missing_hu += 1


            row = {
                "type": item.get("Type"),
                "name": item.get("Name"),
                "series": "",
                "season": "",
                "episode": "",
                "year": item.get(
                    "ProductionYear",
                    ""
                ),
                "path": item.get(
                    "Path",
                    ""
                ),
                "id": item.get(
                    "Id"
                ),
            }


            if item.get("Type") == "Episode":

                row["series"] = item.get(
                    "SeriesName",
                    ""
                )

                row["season"] = item.get(
                    "ParentIndexNumber",
                    ""
                )

                row["episode"] = item.get(
                    "IndexNumber",
                    ""
                )


                print(
                    "[NO HU SUB]",
                    row["series"],
                    f"S{int(row['season'] or 0):02}",
                    f"E{int(row['episode'] or 0):02}",
                    row["name"]
                )


            else:

                print(
                    "[NO HU SUB]",
                    row["name"]
                )


            writer.writerow(row)
            csvfile.flush()


        processed += len(items)
        start += len(items)


        print(
            f"Processed: {processed:,} "
            f"Missing HU subtitles: {missing_hu:,}"
        )



print()
print("=" * 100)
print("Finished")
print(f"Processed: {processed:,}")
print(f"Without Hungarian subtitles: {missing_hu:,}")
print(f"CSV: {OUTPUT_CSV}")