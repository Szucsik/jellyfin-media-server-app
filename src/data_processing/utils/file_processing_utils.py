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

    # ── new: directory-structure season/episode detection ─────────────────────

    def _is_consecutive(self, numbers: list[int]) -> bool:
        """True when the numbers form a gap-free, duplicate-free consecutive run."""
        if len(numbers) < 2:
            return False
        ordered = sorted(numbers)
        if len(set(ordered)) != len(ordered):
            return False  # duplicate season numbers → ambiguous
        return all(ordered[i] + 1 == ordered[i + 1] for i in range(len(ordered) - 1))

    def _extract_season_from_dir(self, directory: str) -> int | None:
        """Extract a season number from a season-level directory name.

        Recognises ``S01`` / ``S1`` / ``Season 1`` / ``Season_01`` style tokens.
        Returns ``None`` when no such token is present.
        """
        name = re.sub(r"[._]", " ", directory)
        m = re.search(r"\b[Ss](?:eason)?\s*0*(\d{1,2})\b", name)
        return int(m.group(1)) if m else None

    def _detect_episode_token_position(
        self, token_lists: list[list[re.Match]]
    ) -> int | None:
        """Find the numeric-token position that encodes episode numbers.

        The episode token is the one whose values are distinct across every file
        and, once sorted, form a gap-free consecutive run (1, 2, 3 …).  Constant
        tokens (release IDs, quality, codecs) and non-sequential tokens are
        ignored.  When several positions qualify, the one closest to episode 1
        wins.
        """
        if not token_lists or any(len(tl) == 0 for tl in token_lists):
            return None

        width = min(len(tl) for tl in token_lists)
        best_pos: int | None = None
        best_start: int | None = None

        for pos in range(width):
            values = [int(tl[pos].group()) for tl in token_lists]
            if len(set(values)) != len(values):
                continue  # not distinct → release ID / quality / season token
            ordered = sorted(values)
            if ordered[-1] > 99:
                continue  # unrealistic episode number → likely a release ID
            if any(ordered[i] + 1 != ordered[i + 1] for i in range(len(ordered) - 1)):
                continue  # not a gap-free sequence
            if best_start is None or ordered[0] < best_start:
                best_start = ordered[0]
                best_pos = pos

        return best_pos

    def _single_file_episode(self, filename: str) -> tuple[int | None, int | None]:
        """Resolve (episode, episode_end) for a lone file via standard parsing."""
        _, episode, episode_end = self.parse_episode(filename)
        if episode is not None:
            return episode, episode_end
        _, episode, episode_end = self.parse_episode_sequence([filename])[0]
        return episode, episode_end

    def _episodes_in_season(
        self, files: list[tuple[str, str]]
    ) -> list[tuple[int, int | None, str, str]]:
        """Resolve episodes for every file inside one season directory.

        ``files`` is a list of ``(original_path, filename)``.  Episodes are taken
        from the numeric token that increases sequentially across the files; when
        no such token exists the method falls back to per-file standard parsing.
        Returns ``(episode, episode_end, original_path, filename)`` for every
        file that could be resolved.
        """
        if not files:
            return []

        if len(files) == 1:
            line, filename = files[0]
            episode, episode_end = self._single_file_episode(filename)
            return [(episode, episode_end, line, filename)] if episode is not None else []

        token_lists = [list(re.finditer(r"\d+", Path(fn).stem)) for _, fn in files]
        position = self._detect_episode_token_position(token_lists)

        resolved: list[tuple[int, int | None, str, str]] = []
        if position is not None:
            for (line, filename), tokens in zip(files, token_lists):
                episode = int(tokens[position].group())
                resolved.append((episode, None, line, filename))
            return resolved

        # No clear sequential token → fall back to per-file standard parsing.
        for line, filename in files:
            episode, episode_end = self._single_file_episode(filename)
            if episode is not None:
                resolved.append((episode, episode_end, line, filename))
        return resolved

    def _detect_structured_seasons(
        self, lines: list[str]
    ) -> tuple[str, str | None, dict[int, list[tuple[str, str]]]] | None:
        """Detect a multi-season layout where season directories form a run.

        Groups video files by their immediate parent directory, extracts a season
        number from each directory and only accepts the layout when those season
        numbers form a gap-free consecutive sequence.  Returns
        ``(show_name, year, {season: [(original_path, filename)]})`` or ``None``
        when no unambiguous season sequence exists (in which case the caller
        falls back to filename-based parsing).
        """
        by_parent: dict[str, list[tuple[str, str]]] = defaultdict(list)
        first_root: str | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split("/")
            filename = parts[-1]
            if Path(filename).suffix.lower() not in VIDEO_EXTS:
                continue
            if self.is_sample(parts) or self.is_excluded_show_directory(parts):
                continue
            if len(parts) < 2:
                continue  # no directory to derive a season from
            if first_root is None:
                first_root = parts[0]
            by_parent[parts[-2]].append((line, filename))

        if len(by_parent) < 2:
            return None  # need at least two season directories for a sequence

        dir_to_season: dict[str, int] = {}
        for directory in by_parent:
            season = self._extract_season_from_dir(directory)
            if season is None:
                return None  # a directory without a season number → ambiguous
            dir_to_season[directory] = season

        if not self._is_consecutive(list(dir_to_season.values())):
            return None

        show_name, year = self.parse_show_info(first_root or "")
        by_season: dict[int, list[tuple[str, str]]] = {
            dir_to_season[directory]: files for directory, files in by_parent.items()
        }
        return show_name, year, by_season

    # ── parser ────────────────────────────────────────────────────────────────

    def parse(self, lines: list[str]) -> list[Show]:
        """
        Parse a list of file paths (or bare filenames) into Show objects.

        Detection order
        ---------------
        0. Directory structure (preferred, unambiguous only): when the media
           files live in season directories whose numbers form a consecutive
           sequence (S01, S02, S03 …), the season number is taken from the
           directory and the episode number from the numeric token that
           increases sequentially across the files in that directory. Unrelated
           numbers (release IDs, quality, codecs) are ignored.
        1. Standard patterns: SxxExx, SxxExx-Exx, NxNN  (parse_episode)
        2. Sequence fallback: compare numeric tokens across files in the same
           show group to identify the varying SEEP token  (parse_episode_sequence)

        Flat-file grouping
        ------------------
        When files have no folder component and ``parse_show_info_from_filename``
        cannot extract a meaningful show name (returns "Unknown"/empty or a name
        that starts with a digit — meaning the episode code was the leading token),
        all such files are collected into a single group and processed jointly by
        the sequence parser.  This covers torrents that use patterns like:

            101_episode.mkv   →  S01E01
            102_asdasd.mkv    →  S01E02
            111.sode.mkv      →  S01E11

        where the increasing 3–4 digit number encodes season and episode.
        """
        raw: dict = defaultdict(lambda: defaultdict(list))

        # Lines already handled by directory-structure detection — skipped below.
        processed: set[str] = set()

        # ── directory-structure detection (preferred when unambiguous) ────────
        structured = self._detect_structured_seasons(lines)
        if structured is not None:
            show_name, year, by_season = structured
            for season_num, files in by_season.items():
                for episode, episode_end, line, filename in self._episodes_in_season(files):
                    ext = Path(filename).suffix.lower()
                    raw[(show_name, year)][season_num].append(
                        Episode(
                            season=season_num,
                            episode=episode,
                            episode_end=episode_end,
                            filename=self.format_ep_filename(show_name, season_num, episode, episode_end, ext),
                            original_path=line,
                        )
                    )
                    processed.add(line)

        # Files that didn't match any standard pattern, keyed by (show, year)
        unresolved: dict[tuple[str, str | None], list[tuple[str, str]]] = defaultdict(list)

        # Flat files (no folder) whose show name couldn't be reliably determined.
        # They are collected together so the sequence parser can use all of them
        # at once — this is critical when each file would otherwise be its own
        # group and the varying numeric token only becomes visible across files.
        flat_unresolved: list[tuple[str, str]] = []  # (original_path, filename)

        for line in lines:
            line = line.strip()
            if not line or line in processed:
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
                # If the show name is garbage (episode code was the first
                # meaningful token so nothing useful was left for the name),
                # defer to the shared flat-file group.
                if show_name in ("Unknown", "") or (show_name and show_name[0].isdigit()):
                    flat_unresolved.append((line, filename))
                    continue

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

        # ── sequence fallback for flat files with undetermined show name ──────
        if flat_unresolved:
            flat_filenames = [filename for _, filename in flat_unresolved]
            seq_results = self.parse_episode_sequence(flat_filenames)

            for (line, filename), (season_num, ep1, ep2) in zip(flat_unresolved, seq_results):
                if season_num is None or ep1 is None:
                    continue
                ext = Path(filename).suffix.lower()
                episode = Episode(
                    season=season_num,
                    episode=ep1,
                    episode_end=ep2,
                    filename=self.format_ep_filename("Unknown", season_num, ep1, ep2, ext),
                    original_path=line,
                )
                raw[("Unknown", None)][season_num].append(episode)

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