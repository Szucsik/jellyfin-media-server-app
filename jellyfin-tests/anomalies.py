#!/usr/bin/env python3
"""
Jellyfin library auditor.

Finds:
  1. Movies that share the same Name (potential duplicates / different versions).
  2. TV Series that share the same Name.
  3. TV Series whose season numbers have "gaps" (e.g. 1, 2, 4, 5 -> missing 3)
     instead of increasing strictly by 1 each time.

Usage:
    python3 anomalies.py --url http://localhost:8096 --api-key XXXX [--user-id XXXX]

Config is resolved in this order (later overrides earlier):
    1. .env file (auto-discovered by walking up from this script's folder)
    2. exported environment variables
    3. CLI flags (--url / --api-key / --user-id)

Put this in your .env (project root, alongside docker-compose.yaml):
    JELLYFIN_URL=http://localhost:8096
    JELLYFIN_API_KEY=your_api_key_here
    JELLYFIN_USER_ID=optional_user_id_here

Requires python-dotenv:
    pip install python-dotenv  (or add it to requirements.txt)

Notes on auth:
  - An API key alone is enough for most GET endpoints via the
    X-Emby-Token header / api_key query param.
  - Some endpoints (notably listing items) are nicer when scoped to a user
    (/Users/{UserId}/Items) so that things like "IsPlayed" etc. resolve
    correctly, but it's optional -- if you don't pass --user-id the script
    falls back to the generic /Items endpoint with Recursive=true.
"""

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def load_env():
    """
    Load environment variables from a .env file.

    Looks for a .env file starting at this script's directory and walking
    up to the project root (so it works whether you run the script from
    the repo root or from jellyfin-tests/). Falls back silently to
    whatever is already in the environment if python-dotenv isn't
    installed or no .env file is found.
    """
    if load_dotenv is None:
        print(
            "Warning: python-dotenv is not installed, so .env will not be loaded "
            "automatically. Install it with: pip install python-dotenv",
            file=sys.stderr,
        )
        return

    here = Path(__file__).resolve().parent
    candidates = [here / ".env"] + [p / ".env" for p in here.parents]

    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(dotenv_path=candidate)
            return

    # No .env found anywhere up the tree -- not fatal, env vars might
    # already be exported in the shell / docker-compose environment.


def get_args():
    load_env()

    p = argparse.ArgumentParser(description="Audit a Jellyfin library for duplicates and season anomalies.")
    p.add_argument("--url", default=os.environ.get("JELLYFIN_URL"), help="Jellyfin server base URL, e.g. http://localhost:8096 (env: JELLYFIN_URL)")
    p.add_argument("--api-key", default=os.environ.get("JELLYFIN_API_KEY"), help="Jellyfin API key (env: JELLYFIN_API_KEY)")
    p.add_argument("--user-id", default=os.environ.get("JELLYFIN_USER_ID"), help="Optional Jellyfin user id to scope item listing to (env: JELLYFIN_USER_ID)")
    p.add_argument("--include-specials", action="store_true", help="Include Season 0 (Specials) in the season-gap check")
    p.add_argument("--ignore-case", action="store_true", help="Case-insensitive name matching for duplicate detection")
    args = p.parse_args()

    if not args.url or not args.api_key:
        p.error(
            "Missing Jellyfin URL/API key. Provide --url/--api-key, or set "
            "JELLYFIN_URL and JELLYFIN_API_KEY in your .env file or environment."
        )

    args.url = args.url.rstrip("/")
    return args


def jf_get(url, api_key, path, params=None):
    params = dict(params or {})
    headers = {"X-Emby-Token": api_key}
    resp = requests.get(f"{url}{path}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_items(url, api_key, user_id, item_type):
    """Fetch all items of a given type (Movie or Series), paging through results."""
    items = []
    start_index = 0
    page_size = 200

    base_path = f"/Users/{user_id}/Items" if user_id else "/Items"

    while True:
        params = {
            "IncludeItemTypes": item_type,
            "Recursive": "true",
            "Fields": "ProviderIds,ProductionYear,Path",
            "StartIndex": start_index,
            "Limit": page_size,
            "SortBy": "SortName",
        }
        data = jf_get(url, api_key, base_path, params)
        batch = data.get("Items", [])
        items.extend(batch)

        total = data.get("TotalRecordCount", len(items))
        start_index += page_size
        if start_index >= total or not batch:
            break

    return items


def fetch_seasons(url, api_key, series_id, user_id):
    params = {}
    if user_id:
        params["userId"] = user_id
    data = jf_get(url, api_key, f"/Shows/{series_id}/Seasons", params)
    return data.get("Items", [])


def find_name_duplicates(items, ignore_case=False):
    groups = defaultdict(list)
    for item in items:
        name = item.get("Name", "")
        key = name.lower() if ignore_case else name
        groups[key].append(item)
    return {name: entries for name, entries in groups.items() if len(entries) > 1}


def find_season_anomalies(url, api_key, series_list, user_id, include_specials=False):
    """
    For each series, fetch its seasons, sort by IndexNumber, and flag any
    place where the season number jumps by more than 1 from the previous one.
    Missing IndexNumber (None) seasons are reported separately as "unnumbered".
    """
    anomalies = {}

    for series in series_list:
        series_id = series["Id"]
        series_name = series.get("Name", "<unknown>")

        try:
            seasons = fetch_seasons(url, api_key, series_id, user_id)
        except requests.HTTPError as e:
            print(f"  ! Failed to fetch seasons for '{series_name}': {e}", file=sys.stderr)
            continue

        numbered = []
        unnumbered = []
        for s in seasons:
            idx = s.get("IndexNumber")
            if idx is None:
                unnumbered.append(s.get("Name", "<no name>"))
            else:
                if idx == 0 and not include_specials:
                    continue
                numbered.append(idx)

        numbered.sort()

        gaps = []
        for prev, curr in zip(numbered, numbered[1:]):
            if curr - prev > 1:
                gaps.append((prev, curr, curr - prev))

        if gaps or unnumbered:
            anomalies[series_name] = {
                "series_id": series_id,
                "season_numbers": numbered,
                "gaps": gaps,
                "unnumbered_seasons": unnumbered,
            }

    return anomalies


def print_duplicates(title, dupes):
    print(f"\n=== {title} ({len(dupes)} duplicate name(s)) ===")
    if not dupes:
        print("  None found.")
        return
    for name, entries in sorted(dupes.items()):
        print(f"\n  '{name}' -> {len(entries)} items:")
        for e in entries:
            year = e.get("ProductionYear", "?")
            path = e.get("Path", "")
            print(f"    - Id={e['Id']} Year={year} Path={path}")


def print_season_anomalies(anomalies):
    print(f"\n=== TV Shows with season numbering anomalies ({len(anomalies)} show(s)) ===")
    if not anomalies:
        print("  None found.")
        return
    for name, info in sorted(anomalies.items()):
        print(f"\n  '{name}' (Id={info['series_id']})")
        print(f"    Season numbers found: {info['season_numbers']}")
        for prev, curr, gap in info["gaps"]:
            print(f"    ANOMALY: jumps from Season {prev} to Season {curr} (gap of {gap})")
        if info["unnumbered_seasons"]:
            print(f"    Unnumbered seasons: {info['unnumbered_seasons']}")


def main():
    args = get_args()

    print(f"Connecting to {args.url} ...")

    print("Fetching all movies...")
    movies = fetch_items(args.url, args.api_key, args.user_id, "Movie")
    print(f"  -> {len(movies)} movies found")

    print("Fetching all TV series...")
    series_list = fetch_items(args.url, args.api_key, args.user_id, "Series")
    print(f"  -> {len(series_list)} series found")

    movie_dupes = find_name_duplicates(movies, ignore_case=args.ignore_case)
    series_dupes = find_name_duplicates(series_list, ignore_case=args.ignore_case)

    print("Checking season numbering for each series (this calls /Shows/{id}/Seasons per series)...")
    season_anomalies = find_season_anomalies(
        args.url, args.api_key, series_list, args.user_id, include_specials=args.include_specials
    )

    print_duplicates("Duplicate Movie Names", movie_dupes)
    print_duplicates("Duplicate TV Show Names", series_dupes)
    print_season_anomalies(season_anomalies)

    print("\nDone.")


if __name__ == "__main__":
    main()