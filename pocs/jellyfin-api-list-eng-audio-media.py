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
OUTPUT_CSV = "jellyfin_real_media_files.csv"

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

session.mount("http://", HTTPAdapter(max_retries=retries))
session.mount("https://", HTTPAdapter(max_retries=retries))


def has_real_media_source(item):
    """
    Returns True if the item has at least one real media file.
    """

    sources = item.get("MediaSources", [])

    if not sources:
        return False

    for source in sources:

        path = (
            source.get("Path")
            or ""
        ).lower()

        if path != PLACEHOLDER_PATH.lower():
            return True

    return False


# =====================================================

start = 0
processed = 0
matches = 0


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
            "container",
            "size",
            "bitrate",
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
                "SeriesName,"
                "ParentIndexNumber,"
                "IndexNumber,"
                "ProductionYear,"
                "Path,"
                "Container"
            ),
            "Limit": PAGE_SIZE,
            "StartIndex": start,
        }


        print(
            f"Fetching "
            f"{start:,} - {start + PAGE_SIZE - 1:,}"
        )


        r = session.get(
            f"{JELLYFIN_URL}/Items",
            headers=HEADERS,
            params=params,
            timeout=(10, 300),
        )

        r.raise_for_status()

        items = r.json().get("Items", [])


        if not items:
            break


        for item in items:

            if not has_real_media_source(item):
                continue


            matches += 1

            source = item["MediaSources"][0]


            row = {
                "type": item.get("Type"),
                "name": item.get("Name"),
                "series": "",
                "season": "",
                "episode": "",
                "year": item.get("ProductionYear", ""),
                "path": source.get("Path", ""),
                "container": item.get("Container", ""),
                "size": source.get("Size", ""),
                "bitrate": source.get("Bitrate", ""),
                "id": item.get("Id"),
            }


            if item["Type"] == "Episode":

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
                    "[Episode]",
                    row["series"],
                    f"S{int(row['season'] or 0):02}",
                    f"E{int(row['episode'] or 0):02}",
                    row["name"],
                )

            else:

                print(
                    "[Movie]",
                    row["name"]
                )


            writer.writerow(row)
            csvfile.flush()


        processed += len(items)
        start += len(items)


        print(
            f"Processed: {processed:,} "
            f"Real media: {matches:,}"
        )


print()
print("=" * 100)
print("Finished")
print(f"Processed: {processed:,}")
print(f"Real media files: {matches:,}")
print(f"CSV: {OUTPUT_CSV}")