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
# HTTP session
# =====================================================

session = requests.Session()

retries = Retry(
    total=5,
    backoff_factor=2,
    status_forcelist=[
        429,
        500,
        502,
        503,
        504,
    ],
    allowed_methods=[
        "GET",
        "POST",
    ],
)

session.mount(
    "http://",
    HTTPAdapter(max_retries=retries)
)

session.mount(
    "https://",
    HTTPAdapter(max_retries=retries)
)


# =====================================================
# HTTP helpers
# =====================================================

def get(url, **kwargs):

    kwargs.setdefault(
        "headers",
        HEADERS
    )

    kwargs.setdefault(
        "timeout",
        (10, 60)
    )

    response = session.get(
        url,
        **kwargs
    )

    response.raise_for_status()

    return response.json()



def post(url, **kwargs):

    kwargs.setdefault(
        "headers",
        HEADERS
    )

    kwargs.setdefault(
        "timeout",
        (10, 60)
    )

    response = session.post(
        url,
        **kwargs
    )

    response.raise_for_status()

    return response



# =====================================================
# Jellyfin helpers
# =====================================================

def has_real_media_source(item):
    """
    Skip Jellyfin placeholder files
    """

    for source in item.get(
        "MediaSources",
        []
    ):

        path = (
            source.get("Path")
            or ""
        ).lower()

        if path != PLACEHOLDER_PATH.lower():
            return True

    return False



def has_hungarian_subtitle(item):
    """
    Returns True if HU subtitles exist
    """

    for stream in item.get(
        "MediaStreams",
        []
    ):

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
# Subtitle downloader
# =====================================================

def download_hungarian_subtitles(
    media_id: str,
    name: str
):

    LANGUAGE = "hu"


    print(
        f"Searching HU subtitles: {name}"
    )


    try:

        subtitle_results = get(
            f"{JELLYFIN_URL}/Items/{media_id}/RemoteSearch/Subtitles/{LANGUAGE}"
        )


    except requests.RequestException as e:

        print(
            f"Subtitle search failed: {name}"
        )

        print(e)

        return



    if not subtitle_results:

        print(
            f"Subtitle NOT found: ({name})"
        )

        return



    print(
        f"Found {len(subtitle_results)} subtitle(s)"
    )


    selected = subtitle_results[0]


    subtitle_id = selected.get(
        "Id"
    )


    if not subtitle_id:

        print(
            f"No subtitle ID: ({name})"
        )

        return



    try:

        post(
            f"{JELLYFIN_URL}/Items/{media_id}/RemoteSearch/Subtitles/{subtitle_id}"
        )


        print(
            f"Subtitle downloaded successfully: ({name})"
        )


    except requests.RequestException as e:

        print(
            f"Subtitle download failed: ({name})"
        )

        print(e)



# =====================================================
# Main scan
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

            "IncludeItemTypes":
                "Movie,Episode",

            "Fields":
                (
                    "MediaSources,"
                    "MediaStreams,"
                    "SeriesName,"
                    "ParentIndexNumber,"
                    "IndexNumber,"
                    "ProductionYear,"
                    "Path"
                ),

            "Limit":
                PAGE_SIZE,

            "StartIndex":
                start,
        }



        print(
            f"Fetching {start:,} - {start + PAGE_SIZE - 1:,}"
        )



        try:

            response = session.get(
                f"{JELLYFIN_URL}/Items",
                headers=HEADERS,
                params=params,
                timeout=(10,60),
            )


            response.raise_for_status()


        except requests.RequestException as e:

            print(
                "Failed loading Jellyfin items:"
            )

            print(e)

            break



        items = response.json().get(
            "Items",
            []
        )



        if not items:

            break



        for item in items:


            if not has_real_media_source(item):

                continue



            if has_hungarian_subtitle(item):

                continue



            missing_hu += 1



            row = {

                "type":
                    item.get("Type"),

                "name":
                    item.get("Name"),

                "series":
                    "",

                "season":
                    "",

                "episode":
                    "",

                "year":
                    item.get(
                        "ProductionYear",
                        ""
                    ),

                "path":
                    item.get(
                        "Path",
                        ""
                    ),

                "id":
                    item.get(
                        "Id",
                        ""
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
                    f"ID={row['id']}",
                    row["series"],
                    f"S{int(row['season'] or 0):02}",
                    f"E{int(row['episode'] or 0):02}",
                    row["name"]
                )


            else:


                print(
                    "[NO HU SUB]",
                    f"ID={row['id']}",
                    row["name"]
                )



            download_hungarian_subtitles(
                row["id"],
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

print(
    f"Processed: {processed:,}"
)

print(
    f"Without Hungarian subtitles: {missing_hu:,}"
)

print(
    f"CSV: {OUTPUT_CSV}"
)