from config import SoPConfig
import requests


# ============================================================
# CONFIG
# ============================================================

JELLYFIN_URL = SoPConfig.JELLYFIN_URL
JELLYFIN_API_KEY = SoPConfig.JELLYFIN_API_KEY
USER_ID = SoPConfig.JELLYFIN_USER

SHOW_NAME = "Happy!"
SEASON_NUMBER = 2
EPISODE_NUMBER = 2


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


def delete(url, **kwargs):
    response = session.delete(url, **kwargs)
    response.raise_for_status()
    return response


# ============================================================
# 1. FIND THE TV SHOW
# ============================================================

print(f"Searching for: {SHOW_NAME}")

data = get(
    f"{JELLYFIN_URL}/Items",
    params={
        "UserId": USER_ID,
        "SearchTerm": SHOW_NAME,
        "IncludeItemTypes": "Series",
        "Recursive": "true",
        "Fields": "ProviderIds",
    }
)

shows = data.get("Items", [])

if not shows:
    raise RuntimeError(
        f"Could not find TV show: {SHOW_NAME}"
    )

show = next(
    (
        x for x in shows
        if x.get("Name", "").lower() == SHOW_NAME.lower()
    ),
    shows[0]
)

series_id = show["Id"]

print(f"Found: {show['Name']}")
print(f"Series ID: {series_id}")


# ============================================================
# 2. FIND EPISODE
# ============================================================

episodes = get(
    f"{JELLYFIN_URL}/Shows/{series_id}/Episodes",
    params={
        "UserId": USER_ID,
        "Season": SEASON_NUMBER,
        "Fields": "Path,ProviderIds,MediaSources,MediaStreams",
        "EnableImages": "false",
    }
).get("Items", [])

episode = next(
    (
        x for x in episodes
        if x.get("IndexNumber") == EPISODE_NUMBER
    ),
    None
)

if not episode:
    raise RuntimeError(
        f"Could not find "
        f"S{SEASON_NUMBER:02d}E{EPISODE_NUMBER:02d}"
    )

episode_id = episode["Id"]

print()
print(
    f"Found episode: "
    f"S{SEASON_NUMBER:02d}E{EPISODE_NUMBER:02d} "
    f"{episode.get('Name', '')}"
)

print(f"Episode ID: {episode_id}")


# ============================================================
# 3. PRINT MEDIA FILE
# ============================================================

print()
print("Media file:")
print(f"  {episode.get('Path')}")

for source in episode.get("MediaSources", []):
    print()
    print("Media source:")
    print(f"  {source.get('Path')}")


# ============================================================
# 4. FIND EXTERNAL SUBTITLES
# ============================================================

subtitle_streams = [
    stream
    for stream in episode.get("MediaStreams", [])
    if stream.get("Type") == "Subtitle"
    and stream.get("IsExternal") is True
]


print()
print(f"Found {len(subtitle_streams)} external subtitle(s):")

for subtitle in subtitle_streams:
    print()
    print(f"Index:       {subtitle.get('Index')}")
    print(f"Language:    {subtitle.get('Language')}")
    print(f"Title:       {subtitle.get('Title')}")
    print(f"Display:     {subtitle.get('DisplayTitle')}")
    print(f"Codec:       {subtitle.get('Codec')}")
    print(f"Path:        {subtitle.get('Path')}")
    print(f"Default:     {subtitle.get('IsDefault')}")
    print(f"Forced:      {subtitle.get('IsForced')}")


# ============================================================
# 5. DELETE EXTERNAL SUBTITLES
# ============================================================

if not subtitle_streams:
    print()
    print("No external subtitles to delete.")
    exit()


print()
print("Deleting external subtitles...")


# Delete highest indexes first.
#
# This is important because after deleting one subtitle,
# Jellyfin may re-number the remaining subtitle streams.
#
# Deleting from highest -> lowest prevents the indexes we
# haven't deleted yet from shifting underneath us.

for subtitle in sorted(
    subtitle_streams,
    key=lambda x: x.get("Index", -1),
    reverse=True
):

    index = subtitle.get("Index")

    print()
    print(
        f"Deleting subtitle "
        f"index={index}, "
        f"language={subtitle.get('Language')}, "
        f"path={subtitle.get('Path')}"
    )

    delete(
        f"{JELLYFIN_URL}/Videos/{episode_id}/Subtitles/{index}"
    )

    print("  ✓ Deleted")


print()
print("Done!")