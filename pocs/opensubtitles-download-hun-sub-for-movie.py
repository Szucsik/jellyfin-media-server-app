from config import SoPConfig
import requests


JELLYFIN_URL = SoPConfig.JELLYFIN_URL
JELLYFIN_API_KEY = SoPConfig.JELLYFIN_API_KEY
USER_ID = SoPConfig.JELLYFIN_USER


MOVIE_NAME = "Dad's Army 2016"

# Hungarian
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
# 1. FIND THE MOVIE
# ============================================================

print(f"Searching for movie: {MOVIE_NAME}")


data = get(
    f"{JELLYFIN_URL}/Items",
    params={
        "UserId": USER_ID,
        "SearchTerm": MOVIE_NAME,
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": (
            "Path,"
            "ProviderIds,"
            "MediaSources,"
            "ProductionYear"
        ),
    }
)


movies = data.get(
    "Items",
    []
)


if not movies:
    raise RuntimeError(
        f"Could not find movie: {MOVIE_NAME}"
    )


# Exact match first
movie = next(
    (
        x for x in movies
        if x.get("Name", "").lower() == MOVIE_NAME.lower()
    ),
    movies[0]
)


movie_id = movie["Id"]


print()
print(f"Found: {movie['Name']}")
print(f"Movie ID: {movie_id}")



# ============================================================
# 2. PRINT MEDIA LOCATION
# ============================================================

movie_path = movie.get(
    "Path"
)

print()
print("Media file:")
print(f"  {movie_path}")


media_sources = movie.get(
    "MediaSources",
    []
)


if media_sources:

    print()
    print("Media sources:")

    for i, source in enumerate(
        media_sources,
        start=1
    ):

        print(
            f"  [{i}] {source.get('Path')}"
        )



# ============================================================
# 3. SEARCH FOR HUNGARIAN SUBTITLES
# ============================================================

print()
print("Searching for Hungarian subtitles...")


subtitle_results = get(
    f"{JELLYFIN_URL}/Items/{movie_id}/RemoteSearch/Subtitles/{LANGUAGE}"
)


print(
    f"Found {len(subtitle_results)} subtitle(s)"
)



# ============================================================
# 4. SHOW RESULTS
# ============================================================

for i, subtitle in enumerate(
    subtitle_results,
    start=1
):

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
# 5. SELECT SUBTITLE
# ============================================================

if not subtitle_results:

    raise RuntimeError(
        "No Hungarian subtitles found for this movie."
    )


selected = subtitle_results[0]


subtitle_id = selected["Id"]


print()
print("Selected subtitle:")
print(selected)



# ============================================================
# 6. DOWNLOAD THROUGH JELLYFIN
# ============================================================

print()
print("Downloading subtitle through Jellyfin...")


post(
    f"{JELLYFIN_URL}/Items/{movie_id}/RemoteSearch/Subtitles/{subtitle_id}"
)


print(
    "Subtitle downloaded successfully!"
)