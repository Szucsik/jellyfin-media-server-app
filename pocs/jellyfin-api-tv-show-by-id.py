from config import SoPConfig
import requests
import json


# ============================================================
# CONFIG
# ============================================================

JELLYFIN_URL = SoPConfig.JELLYFIN_URL
JELLYFIN_API_KEY = SoPConfig.JELLYFIN_API_KEY
USER_ID = SoPConfig.JELLYFIN_USER

SERIES_ID = "ff302adb9a8609762504269fb1601eba"


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "Authorization": f'MediaBrowser Token="{JELLYFIN_API_KEY}"'
})


def get(url, **kwargs):
    response = session.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


# ============================================================
# HELPER
# ============================================================

def print_json(title, data):
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# 1. GET SERIES INFORMATION
# ============================================================

print(f"Getting series information for: {SERIES_ID}")

series = get(
    f"{JELLYFIN_URL}/Items/{SERIES_ID}",
    params={
        "UserId": USER_ID,

        # Ask Jellyfin for as much information as possible
        "Fields": ",".join([
            # "AirTime",
            # "CanDelete",
            # "CanDownload",
            # "ChannelInfo",
            # "CommunityRating",
            # "CriticRating",
            # "CumulativeRunTimeTicks",
            # "CustomRating",
            # "DateCreated",
            # "DateLastMediaAdded",
            # "DisplayPreferencesId",
            # "Etag",
            # "ExternalUrls",
            # "Genres",
            # "HomePageUrl",
            "ItemCounts",
            "MediaSources",
            "MediaStreams",
            "Overview",
            "Path",
            # "People",
            # "PlayAccess",
            # "PremiereDate",
            # "ProductionLocations",
            # "ProviderIds",
            # "PrimaryImageAspectRatio",
            # "RecursiveItemCount",
            # "SeriesStudio",
            # "SortName",
            # "Studios",
            # "Tags",
            # "Taglines",
            # "UserData",
            # "OfficialRating",
            # "OriginalTitle",
            # "ProductionYear",
            # "RemoteTrailers",
        ]),

        "EnableImages": "true",
        "EnableUserData": "true",
        "EnableTotalRecordCount": "true",
        "EnableItemCounts": "true",
    }
)


# ============================================================
# 2. PRINT EVERYTHING JELLYFIN RETURNED FOR SERIES
# ============================================================

print_json("SERIES - COMPLETE API RESPONSE", series)


# ============================================================
# 3. GET SEASONS
# ============================================================

seasons = get(
    f"{JELLYFIN_URL}/Shows/{SERIES_ID}/Seasons",
    params={
        "UserId": USER_ID,

        "Fields": ",".join([
            "AirTime",
            "CommunityRating",
            "CriticRating",
            "DateCreated",
            "Genres",
            "Overview",
            "Path",
            "People",
            "PremiereDate",
            "ProviderIds",
            "SortName",
            "Studios",
            "Tags",
            "Taglines",
            "UserData",
        ]),

        "EnableImages": "true",
        "EnableUserData": "true",
        "EnableTotalRecordCount": "true",
        "EnableItemCounts": "true",
    }
)

print_json("SEASONS - COMPLETE API RESPONSE", seasons)


# ============================================================
# 4. GET EVERY EPISODE
# ============================================================

episodes = get(
    f"{JELLYFIN_URL}/Shows/{SERIES_ID}/Episodes",
    params={
        "UserId": USER_ID,

        "Fields": ",".join([
            "AirTime",
            "CanDelete",
            "CanDownload",
            "ChannelInfo",
            "CommunityRating",
            "CriticRating",
            "CumulativeRunTimeTicks",
            "CustomRating",
            "DateCreated",
            "DateLastMediaAdded",
            "DisplayPreferencesId",
            "Etag",
            "ExternalUrls",
            "Genres",
            "HomePageUrl",
            "ItemCounts",
            "MediaSources",
            "MediaStreams",
            "Overview",
            "Path",
            "People",
            "PlayAccess",
            "PremiereDate",
            "ProductionLocations",
            "ProviderIds",
            "PrimaryImageAspectRatio",
            "SeriesStudio",
            "SortName",
            "Studios",
            "Tags",
            "Taglines",
            "UserData",
            "OfficialRating",
            "OriginalTitle",
            "ProductionYear",
            "RemoteTrailers",
        ]),

        "EnableImages": "true",
        "EnableUserData": "true",
        "EnableTotalRecordCount": "true",
        "EnableItemCounts": "true",

        "Recursive": "true",
    }
)

print_json("EPISODES - COMPLETE API RESPONSE", episodes)


# ============================================================
# 5. PRINT A SMALLER SUMMARY
# ============================================================

print()
print()
print("#" * 100)
print("SUMMARY")
print("#" * 100)

print()
print(f"Series:       {series.get('Name')}")
print(f"Series ID:    {series.get('Id')}")
print(f"Type:         {series.get('Type')}")
print(f"Path:         {series.get('Path')}")
print(f"Year:         {series.get('ProductionYear')}")
print(f"Provider IDs: {series.get('ProviderIds')}")

print()
print(f"Seasons: {len(seasons.get('Items', []))}")
print(f"Episodes: {len(episodes.get('Items', []))}")


# ============================================================
# 6. EPISODE SUMMARY
# ============================================================

for episode in episodes.get("Items", []):

    season = episode.get("ParentIndexNumber")
    episode_number = episode.get("IndexNumber")

    print()
    print(
        f"S{season:02d}E{episode_number:02d} "
        f"{episode.get('Name', '')}"
    )

    print(f"  ID:   {episode.get('Id')}")
    print(f"  Path: {episode.get('Path')}")

    media_sources = episode.get("MediaSources", [])

    for source in media_sources:
        print(
            f"  Media source: "
            f"{source.get('Path')}"
        )

    print(
        f"  Runtime: "
        f"{episode.get('RunTimeTicks')}"
    )

    print(
        f"  Provider IDs: "
        f"{episode.get('ProviderIds')}"
    )