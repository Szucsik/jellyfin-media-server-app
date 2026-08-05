from config import SoPConfig
import requests
import json


# ============================================================
# CONFIG
# ============================================================

JELLYFIN_URL = SoPConfig.JELLYFIN_URL
JELLYFIN_API_KEY = SoPConfig.JELLYFIN_API_KEY
USER_ID = SoPConfig.JELLYFIN_USER

EPISODE_ID = "ca11517094918867818e8d7125bbd112"


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
# GET COMPLETE EPISODE INFORMATION
# ============================================================

print(f"Getting episode information for: {EPISODE_ID}")

episode = get(
    f"{JELLYFIN_URL}/Items/{EPISODE_ID}",
    params={
        "UserId": USER_ID,

        "Fields": ",".join([
            "MediaSources",
            "MediaStreams",
            "Overview",
            "Path",
        ]),

        "EnableImages": "true",
        "EnableUserData": "true",
        "EnableTotalRecordCount": "true",
        "EnableItemCounts": "true",
    }
)


# ============================================================
# PRINT COMPLETE RAW RESPONSE
# ============================================================

print()
print("=" * 100)
print("COMPLETE EPISODE API RESPONSE")
print("=" * 100)

print(
    json.dumps(
        episode,
        indent=2,
        ensure_ascii=False
    )
)


# ============================================================
# BASIC INFORMATION
# ============================================================

print()
print("=" * 100)
print("BASIC INFORMATION")
print("=" * 100)

print(f"Name:             {episode.get('Name')}")
print(f"ID:               {episode.get('Id')}")
print(f"Type:             {episode.get('Type')}")
print(f"Series:           {episode.get('SeriesName')}")
print(f"Series ID:        {episode.get('SeriesId')}")
print(f"Season:           {episode.get('ParentIndexNumber')}")
print(f"Episode:          {episode.get('IndexNumber')}")
print(f"Year:              {episode.get('ProductionYear')}")
print(f"Runtime ticks:    {episode.get('RunTimeTicks')}")
print(f"Path:             {episode.get('Path')}")
print(f"Container:        {episode.get('Container')}")
print(f"Provider IDs:     {episode.get('ProviderIds')}")


# ============================================================
# MEDIA SOURCES
# ============================================================

print()
print("=" * 100)
print("MEDIA SOURCES")
print("=" * 100)

media_sources = episode.get("MediaSources", [])

if not media_sources:
    print("No media sources returned.")

for i, source in enumerate(media_sources, start=1):

    print()
    print(f"--- MEDIA SOURCE {i} ---")

    print(f"ID:                 {source.get('Id')}")
    print(f"Name:               {source.get('Name')}")
    print(f"Path:               {source.get('Path')}")
    print(f"Container:          {source.get('Container')}")
    print(f"Size:               {source.get('Size')}")
    print(f"Protocol:           {source.get('Protocol')}")
    print(f"Type:               {source.get('Type')}")
    print(f"Bitrate:            {source.get('Bitrate')}")
    print(f"RunTimeTicks:       {source.get('RunTimeTicks')}")
    print(f"ETag:               {source.get('ETag')}")
    print(f"SupportsTranscoding:{source.get('SupportsTranscoding')}")
    print(f"SupportsDirectPlay: {source.get('SupportsDirectPlay')}")
    print(f"SupportsDirectStream:{source.get('SupportsDirectStream')}")


# ============================================================
# MEDIA STREAMS
# ============================================================

print()
print("=" * 100)
print("MEDIA STREAMS")
print("=" * 100)

streams = episode.get("MediaStreams", [])

if not streams:
    print("No media streams returned.")

for i, stream in enumerate(streams, start=1):

    print()
    print(f"--- STREAM {i} ---")

    print(f"Index:              {stream.get('Index')}")
    print(f"Type:               {stream.get('Type')}")
    print(f"Codec:              {stream.get('Codec')}")
    print(f"Language:           {stream.get('Language')}")
    print(f"Title:              {stream.get('Title')}")
    print(f"DisplayTitle:       {stream.get('DisplayTitle')}")
    print(f"IsDefault:          {stream.get('IsDefault')}")
    print(f"IsForced:           {stream.get('IsForced')}")
    print(f"IsExternal:         {stream.get('IsExternal')}")
    print(f"IsTextSubtitleStream:{stream.get('IsTextSubtitleStream')}")
    print(f"IsHearingImpaired:  {stream.get('IsHearingImpaired')}")
    print(f"Path:               {stream.get('Path')}")
    print(f"CodecTag:           {stream.get('CodecTag')}")
    print(f"Profile:            {stream.get('Profile')}")
    print(f"Level:              {stream.get('Level')}")
    print(f"BitRate:            {stream.get('BitRate')}")
    print(f"Width:              {stream.get('Width')}")
    print(f"Height:             {stream.get('Height')}")
    print(f"Channels:           {stream.get('Channels')}")
    print(f"SampleRate:         {stream.get('SampleRate')}")


# ============================================================
# SUBTITLE STREAMS ONLY
# ============================================================

print()
print("=" * 100)
print("SUBTITLE STREAMS")
print("=" * 100)

subtitle_streams = [
    stream
    for stream in streams
    if stream.get("Type") == "Subtitle"
]

if not subtitle_streams:
    print("No subtitle streams found.")

for i, subtitle in enumerate(subtitle_streams, start=1):

    print()
    print(f"--- SUBTITLE {i} ---")

    print(f"Index:              {subtitle.get('Index')}")
    print(f"Language:           {subtitle.get('Language')}")
    print(f"Title:              {subtitle.get('Title')}")
    print(f"DisplayTitle:       {subtitle.get('DisplayTitle')}")
    print(f"Codec:              {subtitle.get('Codec')}")
    print(f"Path:               {subtitle.get('Path')}")
    print(f"IsDefault:          {subtitle.get('IsDefault')}")
    print(f"IsForced:           {subtitle.get('IsForced')}")
    print(f"IsExternal:         {subtitle.get('IsExternal')}")
    print(
        f"IsHearingImpaired:  "
        f"{subtitle.get('IsHearingImpaired')}"
    )


# ============================================================
# USER DATA
# ============================================================

print()
print("=" * 100)
print("USER DATA")
print("=" * 100)

print(
    json.dumps(
        episode.get("UserData"),
        indent=2,
        ensure_ascii=False
    )
)


# ============================================================
# PEOPLE
# ============================================================

print()
print("=" * 100)
print("PEOPLE")
print("=" * 100)

for person in episode.get("People", []):

    print(
        f"{person.get('Type'):15} | "
        f"{person.get('Name'):30} | "
        f"{person.get('Role', '')}"
    )


# ============================================================
# IMAGES
# ============================================================

print()
print("=" * 100)
print("IMAGE INFORMATION")
print("=" * 100)

print(
    json.dumps(
        episode.get("ImageTags"),
        indent=2,
        ensure_ascii=False
    )
)


# ============================================================
# CHAPTERS
# ============================================================

print()
print("=" * 100)
print("CHAPTERS")
print("=" * 100)

for chapter in episode.get("Chapters", []):

    print(
        f"Start: {chapter.get('StartPositionTicks')} | "
        f"Name: {chapter.get('Name')}"
    )
