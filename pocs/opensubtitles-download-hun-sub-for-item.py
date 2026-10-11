from config import SoPConfig
import requests

JELLYFIN_URL = SoPConfig.JELLYFIN_URL
JELLYFIN_API_KEY = SoPConfig.JELLYFIN_API_KEY
USER_ID = SoPConfig.JELLYFIN_USER

SHOW_NAME = "Happy!"
SEASON_NUMBER = 2
EPISODE_NUMBER = 11

# Hungarian
LANGUAGE = "hu"


# ============================================================ e02a34f56233e3e5e7765144ca8f184f_srt-HU-4925278
# HTTP SESSION
# ============================================================ e02a34f56233e3e5e7765144ca8f184f_srt-hu-4925278

session = requests.Session()

session.headers.update({
    "Authorization": f'MediaBrowser Token="{JELLYFIN_API_KEY}"'
})


def get(url, **kwargs):
    response = session.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


def post(url, **kwargs):
    response = session.post(url, **kwargs)
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
    raise RuntimeError(f"Could not find TV show: {SHOW_NAME}")

# Try to find an exact match first
show = next(
    (x for x in shows if x.get("Name", "").lower() == SHOW_NAME.lower()),
    shows[0]
)

series_id = show["Id"]

print(f"Found: {show['Name']}")
print(f"Series ID: {series_id}")


# ============================================================
# 2. FIND SEASON 2 EPISODE 10
# ============================================================

episodes = get(
    f"{JELLYFIN_URL}/Shows/{series_id}/Episodes",
    params={
        "UserId": USER_ID,
        "Season": SEASON_NUMBER,
        "Fields": "Path,ProviderIds,MediaSources",
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
        f"Could not find S{SEASON_NUMBER:02d}E{EPISODE_NUMBER:02d}"
    )

episode_id = episode["Id"]

print(
    f"Found episode: "
    f"S{SEASON_NUMBER:02d}E{EPISODE_NUMBER:02d} "
    f"{episode.get('Name', '')}"
)
print(f"Episode ID: {episode_id}")


# ============================================================
# 2.3. PRINT MEDIA FILE LOCATION
# ============================================================

episode_path = episode.get("Path")

print()
print("Media file:")
print(f"  {episode_path}")

# MediaSources can also contain the media path
media_sources = episode.get("MediaSources", [])

if media_sources:
    print()
    print("Media sources:")

    for i, source in enumerate(media_sources, start=1):
        source_path = source.get("Path")

        print(f"  [{i}] {source_path}")

# ============================================================
# 3. SEARCH FOR HUNGARIAN SUBTITLES
# ============================================================

print("Searching for Hungarian subtitles...")

subtitle_results = get(
    f"{JELLYFIN_URL}/Items/{episode_id}/RemoteSearch/Subtitles/{LANGUAGE}"
)

print(f"Found {len(subtitle_results)} subtitle(s)")


# ============================================================
# 4. SHOW RESULTS
# ============================================================

for i, subtitle in enumerate(subtitle_results, start=1):
    print()
    print(f"[{i}]")
    print("ID:       ", subtitle.get("Id"))
    print("Provider: ", subtitle.get("Provider"))
    print("Name:     ", subtitle.get("Name"))
    print("Language: ", subtitle.get("Language"))
    print("Format:   ", subtitle.get("Format"))
    print("IsForced: ", subtitle.get("IsForced"))
    print("IsSDH:    ", subtitle.get("IsSDH"))
    print("Hearing:  ", subtitle.get("IsHearingImpaired"))
    print("Comment:  ", subtitle.get("Comment"))


# ============================================================
# 5. SELECT A SUBTITLE
# ============================================================

if not subtitle_results:
    raise RuntimeError(
        "No Hungarian subtitles found for this episode."
    )

# For now, simply choose the first result.
selected = subtitle_results[0]

subtitle_id = selected["Id"]

print()
print("Selected subtitle:")
print(selected)


# ============================================================
# 6. DOWNLOAD THROUGH JELLYFIN
# ============================================================

print("Downloading subtitle through Jellyfin...")

post(
    f"{JELLYFIN_URL}/Items/{episode_id}/RemoteSearch/Subtitles/{subtitle_id}"
)

print("Subtitle downloaded successfully!")