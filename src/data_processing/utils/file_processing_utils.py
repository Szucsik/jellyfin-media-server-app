#!/usr/bin/env python3
from __future__ import annotations

import re
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

# ── helpers ───────────────────────────────────────────────────────────────────
class FileProcessingUtils:
    """a"""
    def __init__(self):
        pass

    def is_sample(self, path_parts: list[str]) -> bool:
        """a"""
        return any(re.fullmatch(r"[Ss]ample.*", p) for p in path_parts)


    def parse_show_info(self, folder: str) -> tuple[str, str | None]:
        """a"""
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
        """a"""
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
        """a"""
        base = f"{show} S{season:02d}E{ep1:02d}"
        if ep2 is not None:
            base += f"-E{ep2:02d}"
        return base + ext


    # ── parser ────────────────────────────────────────────────────────────────────

    def parse(self, lines: list[str]) -> list[Show]:
        """a"""
        # Intermediate: { (name, year): { season_num: [Episode, ...] } }
        raw: dict = defaultdict(lambda: defaultdict(list))

        for line in lines:
            line = line.strip()
            if not line:
                continue

            path_parts = line.split("/")
            filename = path_parts[-1]
            ext = Path(filename).suffix.lower()

            if ext not in VIDEO_EXTS:
                continue
            if self.is_sample(path_parts):
                continue

            show_name, year = self.parse_show_info(path_parts[0])
            season_num, ep1, ep2 = self.parse_episode(filename)

            if season_num is None or ep1 is None:
                continue

            episode = Episode(
                season=season_num,
                episode=ep1,
                episode_end=ep2,
                filename=self.format_ep_filename(show_name, season_num, ep1, ep2, ext),
                original_path=line,
            )
            raw[(show_name, year)][season_num].append(episode)

        shows = []
        for (name, year), seasons_dict in sorted(raw.items()):
            seasons = [
                Season(number=num, episodes=sorted(eps, key=lambda e: e.episode))
                for num, eps in sorted(seasons_dict.items())
            ]
            shows.append(Show(name=name, year=year, seasons=seasons))

        return shows


    def get_show(self, files: list[str]) -> list[Show]:
        """a"""
        return self.parse(files)