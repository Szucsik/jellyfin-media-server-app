from config import SoPConfig
import requests
import time


JELLYFIN_URL = SoPConfig.JELLYFIN_URL
JELLYFIN_API_KEY = SoPConfig.JELLYFIN_API_KEY
USER_ID = SoPConfig.JELLYFIN_USER

SHOW_NAME = "Happy!"
LANGUAGE = "hu"


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


def post(url, **kwargs):
    response = session.post(url, **kwargs)
    response.raise_for_status()
    return response


# ============================================================
# FIND TV SHOW
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

print()
print(f"Found: {show['Name']}")
print(f"Series ID: {series_id}")


# ============================================================
# GET ALL EPISODES
# ============================================================

print()
print("Loading episodes...")


episodes = get(
    f"{JELLYFIN_URL}/Shows/{series_id}/Episodes",
    params={
        "UserId": USER_ID,
        "Recursive": "true",
        "Fields": (
            "MediaStreams,"
            "MediaSources,"
            "Path"
        ),
        "EnableImages": "false",
    }
).get("Items", [])


print(
    f"Found {len(episodes)} episodes"
)


# ============================================================
# PROCESS EPISODES
# ============================================================

downloaded = 0
skipped = 0
failed = 0


for index, episode in enumerate(episodes, start=1):

    season = episode.get("ParentIndexNumber", 0)
    number = episode.get("IndexNumber", 0)
    name = episode.get("Name", "")

    episode_id = episode["Id"]


    print()
    print("=" * 70)
    print(
        f"[{index}/{len(episodes)}] "
        f"S{season:02}E{number:02} {name}"
    )


    # --------------------------------------------------------
    # Check existing Hungarian subtitles
    # --------------------------------------------------------

    has_hun = False

    for stream in episode.get("MediaStreams", []):

        if stream.get("Type") != "Subtitle":
            continue

        lang = (
            stream.get("Language")
            or ""
        ).lower()

        if lang in ("hu", "hun"):
            has_hun = True
            break


    if has_hun:
        print(
            "Already has Hungarian subtitles. Skipping."
        )
        skipped += 1
        continue


    # --------------------------------------------------------
    # Search subtitles
    # --------------------------------------------------------

    try:

        print(
            "Searching Hungarian subtitles..."
        )

        subtitle_results = get(
            f"{JELLYFIN_URL}/Items/"
            f"{episode_id}/RemoteSearch/Subtitles/{LANGUAGE}"
        )


        if not subtitle_results:

            print(
                "No Hungarian subtitles found."
            )

            failed += 1
            continue


        subtitle = subtitle_results[0]

        subtitle_id = subtitle["Id"]


        print(
            "Downloading:",
            subtitle.get("Name"),
            subtitle.get("Format")
        )


        post(
            f"{JELLYFIN_URL}/Items/"
            f"{episode_id}/RemoteSearch/"
            f"Subtitles/{subtitle_id}"
        )


        print(
            "Downloaded successfully"
        )

        downloaded += 1


        # Give Jellyfin/OpenSubtitles a little time
        time.sleep(1)


    except Exception as e:

        print(
            "ERROR:",
            e
        )

        failed += 1



# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 70)
print("Finished")
print()
print(f"Downloaded : {downloaded}")
print(f"Skipped    : {skipped}")
print(f"Failed     : {failed}")