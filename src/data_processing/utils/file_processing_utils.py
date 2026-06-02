#!/usr/bin/env python3
from __future__ import annotations

import re
import requests
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class Episode:
    season: int
    episode: int
    episode_end: int | None   # set for multi-episode files (e.g. E01-E02)
    filename: str             # normalised filename
    original_path: str        # original path as received from qBittorrent


@dataclass
class Season:
    number: int
    episodes: list[Episode] = field(default_factory=list)


@dataclass
class Show:
    name: str
    year: str | None
    seasons: list[Season] = field(default_factory=list)


# ── constants ─────────────────────────────────────────────────────────────────

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".mov"}
EXCLUDED_SHOW_DIRS = {"sample", "samples", "extra", "extras"}

# Matches quality/source tokens that appear before the show name in flat filenames
# e.g. "sln-720p", "1080p", "WEBRip", "BluRay"
QUALITY_RE = re.compile(
    r'\b(?:\d{3,4}p|4k|uhd|hdr|bluray|blu-ray|webrip|web-dl|hdtv|amzn|nf|dsnp|hmax)\b',
    re.I,
)


# ── helpers ───────────────────────────────────────────────────────────────────

class FileProcessingUtils:

    def __init__(self):
        pass

    # ── existing helpers ──────────────────────────────────────────────────────

    def is_sample(self, path_parts: list[str]) -> bool:
        return any(re.fullmatch(r"[Ss]ample.*", p) for p in path_parts)

    def is_excluded_show_directory(self, path_parts: list[str]) -> bool:
        """Exclude files under non-standard show directories (case-insensitive)."""
        if len(path_parts) <= 1:
            return False
        directories = path_parts[:-1]
        return any(part.lower() in EXCLUDED_SHOW_DIRS for part in directories)

    def parse_show_info(self, folder: str) -> tuple[str, str | None]:
        """Parse show name and year from a folder name."""
        name = re.sub(r"[._]", " ", folder)
        year_m = re.search(r"\b((?:19|20)\d{2})\b", name)
        year = year_m.group(1) if year_m else None
        clean = re.split(r"\s+[Ss]\d{1,2}\b", name)[0]
        if year:
            clean = clean.split(year)[0]
        clean = re.sub(r"[\s\-]+$", "", clean)
        show_name = " ".join(w.capitalize() for w in clean.split())
        return show_name, year

    def parse_episode(self, filename: str) -> tuple[int | None, int | None, int | None]:
        """Parse season/episode from a filename using standard naming patterns."""
        stem = Path(filename).stem

        m = re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})(?:-?[Ee](\d{1,2}))?", stem)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None

        m = re.search(r"[Ss](\d{1,2})\.?[Ee](\d{1,2})", stem)
        if m:
            return int(m.group(1)), int(m.group(2)), None

        m = re.search(r"(\d{1,2})x(\d{2})", stem)
        if m:
            return int(m.group(1)), int(m.group(2)), None

        return None, None, None

    def format_ep_filename(self, show: str, season: int, ep1: int, ep2: int | None, ext: str) -> str:
        base = f"{show} S{season:02d}E{ep1:02d}"
        if ep2 is not None:
            base += f"-E{ep2:02d}"
        return base + ext

    # ── new: flat-filename show name parser ───────────────────────────────────

    def parse_show_info_from_filename(self, filename: str) -> tuple[str, str | None]:
        """
        Extract show name and year from a bare filename (no folder path).

        Handles patterns like:
            sln-720p.yellowstone.401.mkv  →  ("Yellowstone", None)
            grp.1080p.breaking.bad.2008.512.mkv  →  ("Breaking Bad", "2008")

        Strategy:
        - Split stem on dots
        - Locate the quality/group token (contains e.g. 720p) — everything
          before it is a release-group prefix we discard
        - Locate the first episode-number token (3–4 bare digits or SxxExx) —
          everything from that point onward is episode/codec metadata we discard
        - What remains between those two boundaries is the show name
        """
        stem = Path(filename).stem
        parts = stem.split(".")

        quality_idx: int | None = None
        ep_idx: int | None = None

        for i, part in enumerate(parts):
            if quality_idx is None and QUALITY_RE.search(part):
                quality_idx = i
            # Episode token: bare 3–4 digit number (e.g. 401, 1205) or SxxExx
            if ep_idx is None and re.fullmatch(r"\d{3,4}", part):
                ep_idx = i
                break
            if ep_idx is None and re.search(r"[Ss]\d{1,2}[Ee]\d{1,2}", part):
                ep_idx = i
                break

        start = (quality_idx + 1) if quality_idx is not None else 0
        end = ep_idx if ep_idx is not None else len(parts)

        show_parts = parts[start:end]
        year: str | None = None
        filtered: list[str] = []
        for p in show_parts:
            if re.fullmatch(r"(?:19|20)\d{2}", p):
                year = p
            else:
                filtered.append(p)

        raw_name = " ".join(filtered).replace("-", " ")
        show_name = " ".join(w.capitalize() for w in raw_name.split()) or "Unknown"
        return show_name, year

    # ── new: sequence-based episode parser ───────────────────────────────────

    def parse_episode_sequence(
        self, filenames: list[str]
    ) -> list[tuple[int | None, int | None, int | None]]:
        """
        Fallback episode parser for groups of files that share a common naming
        template where a combined season+episode token changes between files.

        Algorithm
        ---------
        1. Extract every numeric token from each filename stem.
        2. For each token position, check whether its value differs across the
           group — tokens that vary are the episode-encoding candidates.
        3. Concatenate the varying token values and interpret the resulting
           number as SEEP (e.g. 401 → S04E01, 1205 → S12E05).
        4. If no token varies (single-file group), fall back to the last
           numeric token in the stem.

        Examples
        --------
        sln-720p.yellowstone.401.mkv … .410.mkv  →  S04E01 … S04E10
        grp.1080p.show.212.mkv … .220.mkv        →  S02E12 … S02E20
        """
        stems = [Path(f).stem for f in filenames]
        token_lists = [list(re.finditer(r"\d+", s)) for s in stems]

        if not token_lists or not token_lists[0]:
            return [(None, None, None)] * len(filenames)

        n_tokens = len(token_lists[0])

        # Token positions whose value differs across at least two files
        varying_indices = [
            ti
            for ti in range(n_tokens)
            if len({tl[ti].group() for tl in token_lists if ti < len(tl)}) > 1
        ]

        # Single-file or identical group: fall back to the last numeric token
        if not varying_indices:
            varying_indices = [len(token_lists[0]) - 1]

        results: list[tuple[int | None, int | None, int | None]] = []
        for tl in token_lists:
            combined = "".join(
                tl[ti].group() for ti in varying_indices if ti < len(tl)
            )
            if not combined:
                results.append((None, None, None))
                continue

            num = int(combined)

            if num >= 100:
                # e.g. 401 → season=4, episode=1
                season = num // 100
                episode = num % 100
                if episode == 0:
                    # 400-style is ambiguous; skip
                    results.append((None, None, None))
                else:
                    results.append((season, episode, None))
            elif num > 0:
                # Only episode number visible (season must come from elsewhere)
                results.append((None, num, None))
            else:
                results.append((None, None, None))

        return results

    # ── parser ────────────────────────────────────────────────────────────────

    def parse(self, lines: list[str]) -> list[Show]:
        """
        Parse a list of file paths (or bare filenames) into Show objects.

        Episode detection order
        -----------------------
        1. Standard patterns: SxxExx, SxxExx-Exx, NxNN  (parse_episode)
        2. Sequence fallback: compare numeric tokens across files in the same
           show group to identify the varying SEEP token  (parse_episode_sequence)
        """
        raw: dict = defaultdict(lambda: defaultdict(list))

        # Files that didn't match any standard pattern, keyed by (show, year)
        unresolved: dict[tuple[str, str | None], list[tuple[str, str]]] = defaultdict(list)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            path_parts = line.split("/")
            filename = path_parts[-1]
            ext = Path(filename).suffix.lower()

            if ext not in VIDEO_EXTS:
                continue
            if self.is_sample(path_parts) or self.is_excluded_show_directory(path_parts):
                continue

            # Use folder name when available; fall back to filename-level parsing
            if len(path_parts) >= 2:
                show_name, year = self.parse_show_info(path_parts[0])
            else:
                show_name, year = self.parse_show_info_from_filename(filename)

            season_num, ep1, ep2 = self.parse_episode(filename)

            if season_num is None or ep1 is None:
                unresolved[(show_name, year)].append((line, filename))
                continue

            episode = Episode(
                season=season_num,
                episode=ep1,
                episode_end=ep2,
                filename=self.format_ep_filename(show_name, season_num, ep1, ep2, ext),
                original_path=line,
            )
            raw[(show_name, year)][season_num].append(episode)

        # ── sequence fallback for unresolved files ────────────────────────────
        for (show_name, year), group in unresolved.items():
            filenames = [filename for _, filename in group]
            seq_results = self.parse_episode_sequence(filenames)

            for (line, filename), (season_num, ep1, ep2) in zip(group, seq_results):
                if season_num is None or ep1 is None:
                    continue
                ext = Path(filename).suffix.lower()
                episode = Episode(
                    season=season_num,
                    episode=ep1,
                    episode_end=ep2,
                    filename=self.format_ep_filename(show_name, season_num, ep1, ep2, ext),
                    original_path=line,
                )
                raw[(show_name, year)][season_num].append(episode)

        # ── assemble Show objects ─────────────────────────────────────────────
        shows = []
        for (name, year), seasons_dict in sorted(raw.items()):
            seasons = [
                Season(number=num, episodes=sorted(eps, key=lambda e: e.episode))
                for num, eps in sorted(seasons_dict.items())
            ]
            shows.append(Show(name=name, year=year, seasons=seasons))

        return shows


    def get_name_by_id_from_tmdb(self, imdb_id: str, api_key: str) -> str:
        """Get movie or show name by imdb id"""
        url = f"https://api.themoviedb.org/3/find/{imdb_id}"
        params = {
            "api_key": api_key,
            "external_source": "imdb_id"
        }

        response = requests.get(url, params=params, timeout=10)
        data = response.json()

        # Check movies first, then TV shows
        if data["movie_results"]:
            return f"{data['movie_results'][0]['title']} [imdbid-{imdb_id}]"
        elif data["tv_results"]:
            return f"{data['tv_results'][0]['name']} [imdbid-{imdb_id}]"
        else:
            return ""


    def get_show(self, files: list[str]) -> list[Show]:
        return self.parse(files)