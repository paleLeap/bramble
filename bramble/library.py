"""Scanning library folders into items the window can list and open."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import kinds, paths

BUSY_SECONDS = 90
PARTIAL_SUFFIXES = (".!qb", ".part", ".crdownload", ".download", ".partial", ".tmp")
MIN_MOVIE = 50 * 1024 * 1024
GROUPING = {"pc", "windows", "linux", "games", "roms", "retro", "emulation"}


@dataclass
class Item:
    path: Path                 # the file, or the folder for a folder game/program
    kind: str
    category: str
    root: Path                 # the MARROW (or other) root it was found under
    title: str
    year: str | None = None
    size: int = 0
    mtime: float = 0.0
    busy: bool = False         # still downloading or being copied
    exe: Path | None = None    # for folder games/programs: the file that starts it
    system: kinds.System | None = None
    episode: kinds.Episode | None = None
    album: str = ""
    sidecar_subs: list[Path] = field(default_factory=list)

    @property
    def target(self) -> Path:
        return self.exe or self.path

    @property
    def key(self) -> str:
        return str(self.path)

    @property
    def display(self) -> str:
        if self.episode:
            e = self.episode
            t = f" · {e.title}" if e.title else ""
            return f"S{e.season:02d}E{e.number:02d}{t}"
        return f"{self.title} ({self.year})" if self.year else self.title


def _is_busy(p: Path, st: os.stat_result) -> bool:
    return p.name.lower().endswith(PARTIAL_SUFFIXES) or (time.time() - st.st_mtime) < BUSY_SECONDS


def _strip_partial(p: Path) -> Path:
    low = p.name.lower()
    for s in PARTIAL_SUFFIXES:
        if low.endswith(s):
            return p.with_name(p.name[: -len(s)])
    return p


def _folder_size(folder: Path, limit: int = 20000) -> tuple[int, float]:
    total, newest, n = 0, 0.0, 0
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            try:
                st = os.stat(os.path.join(dirpath, f))
            except OSError:
                continue
            total += st.st_size
            newest = max(newest, st.st_mtime)
            n += 1
            if n >= limit:
                return total, newest
    return total, newest


def _subs_beside(video: Path) -> list[Path]:
    out = []
    stem = video.stem.lower()
    try:
        for p in video.parent.iterdir():
            if p.suffix.lower() in kinds.SUBTITLE and p.name.lower().startswith(stem[:20]):
                out.append(p)
        for sub in ("Subs", "subs", "Subtitles", "subtitles"):
            d = video.parent / sub
            if d.is_dir():
                out.extend(p for p in d.rglob("*") if p.suffix.lower() in kinds.SUBTITLE)
    except OSError:
        pass
    return out


def _file_item(p: Path, category: str, root: Path) -> Item | None:
    try:
        st = p.stat()
    except OSError:
        return None
    real = _strip_partial(p)
    kind = kinds.classify(real, category)
    if kind in ("movie", "episode"):
        if "sample" in real.stem.lower() or (st.st_size < MIN_MOVIE and category != "TV Shows"
                                              and kind == "movie"):
            return None
    title, year = kinds.nice_title(real)
    it = Item(path=p, kind=kind, category=category, root=root, title=title, year=year,
              size=st.st_size, mtime=st.st_mtime, busy=_is_busy(p, st))
    if kind == "episode":
        it.episode = kinds.episode_info(real)
        if it.episode:
            it.title = it.episode.show
            it.year = None
    if kind in ("movie", "episode"):
        it.sidecar_subs = _subs_beside(p)
    if kind == "rom":
        it.system = kinds.system_for(real)
    if kind == "music":
        it.album = p.parent.name if p.parent != root / category else ""
        it.title = kinds._tidy(real.stem)
        it.year = None
    if kind == "rom":
        # "Super Metroid (USA) [!]" -> "Super Metroid"
        it.title = re.sub(r"\s*[\[(][^\])]*[\])]", "", kinds._tidy(real.stem)).strip() or real.stem
        it.year = None
    elif kind in ("game_windows", "game_linux", "program", "installer", "other",
                  "image", "document", "archive"):
        # Keep dots here: they are usually version numbers ("Some.App-1.2").
        it.title = re.sub(r"[_]+", " ", real.stem).strip() or real.name
        it.year = None
    return it


def _folder_game(d: Path, category: str, root: Path) -> Item | None:
    exe = kinds.main_executable(d)
    kind = "game_windows" if category == "Video Games" else "program"
    if exe is None:
        exe = kinds.main_linux_executable(d)
        kind = "game_linux" if category == "Video Games" else "program"
    if exe is None:
        return None
    size, newest = _folder_size(d)
    title = kinds._tidy(d.name)
    title = re.sub(r"(?i)\s*[\[(](fitgirl|dodi|elamigos|gog|repack|portable)[^\])]*[\])]", "", title).strip()
    return Item(path=d, kind=kind, category=category, root=root, title=title or d.name,
                size=size, mtime=newest, busy=(time.time() - newest) < BUSY_SECONDS, exe=exe)


def _is_grouping(d: Path) -> bool:
    low = d.name.lower()
    if low in GROUPING:
        return True
    return any(low == w or low == s.name.lower() for s in kinds.SYSTEMS for w in s.folder_words)


def _scan_games_like(folder: Path, category: str, root: Path, depth: int = 0) -> list[Item]:
    items: list[Item] = []
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return items
    for p in entries:
        if p.name.startswith("."):
            continue
        if p.is_dir():
            if depth < 3 and (_is_grouping(p) or depth == 0 and not _looks_like_app(p)):
                items.extend(_scan_games_like(p, category, root, depth + 1))
            else:
                it = _folder_game(p, category, root)
                if it:
                    items.append(it)
                elif depth < 3:
                    items.extend(_scan_games_like(p, category, root, depth + 1))
        elif p.is_file():
            it = _file_item(p, category, root)
            if it and it.kind not in ("other", "image", "document") or (it and category == "Programs"):
                items.append(it)
    return items


def _looks_like_app(d: Path) -> bool:
    try:
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in (".exe", ".x86_64", ".appimage"):
                return True
        return any(p.is_dir() for p in d.iterdir()) and kinds.main_executable(d) is not None
    except OSError:
        return False


def _scan_media(folder: Path, category: str, root: Path) -> list[Item]:
    items: list[Item] = []
    for dirpath, dirnames, files in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            p = Path(dirpath) / f
            ext = _strip_partial(p).suffix.lower()
            if category in ("Movies", "TV Shows") and ext not in kinds.VIDEO:
                continue
            if category == "Music" and ext not in kinds.AUDIO and ext not in kinds.VIDEO:
                continue
            it = _file_item(p, category, root)
            if it:
                items.append(it)
    return items


def scan_root(root: Path) -> list[Item]:
    items: list[Item] = []
    for category in paths.CATEGORIES:
        folder = root / category
        if not folder.is_dir():
            continue
        if category in ("Video Games", "Programs"):
            items.extend(_scan_games_like(folder, category, root))
        else:
            items.extend(_scan_media(folder, category, root))
    return items


def library_roots(settings) -> list[Path]:
    roots: list[Path] = []
    for drive in paths.find_drives():
        roots.append(paths.drive_marrow(drive))
    local = paths.local_marrow()
    if local.is_dir() or not roots:
        roots.append(local)
    for extra in settings["library_roots"]:
        p = Path(extra)
        if p not in roots:
            roots.append(p)
    return roots


def scan(settings) -> list[Item]:
    out: list[Item] = []
    for root in library_roots(settings):
        if root.is_dir():
            out.extend(scan_root(root))
    return out


def scan_inbox(settings, library_items: list[Item]) -> list[Item]:
    """Media, games and programs sitting in Downloads that are not in the library yet."""
    known = {str(i.path) for i in library_items}
    out: list[Item] = []
    for folder in settings.inbox_folders():
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.name.startswith(".") or str(p) in known:
                continue
            if p.is_dir():
                vids = [v for v in p.rglob("*") if v.is_file()
                        and _strip_partial(v).suffix.lower() in kinds.VIDEO]
                vids = [v for v in vids if "sample" not in v.name.lower()]
                if vids:
                    for v in vids:
                        it = _file_item(v, None, folder)
                        if it:
                            it.category = kinds.CATEGORY_FOR_KIND[it.kind]
                            out.append(it)
                    continue
                g = _folder_game(p, "Video Games", folder)
                if g:
                    out.append(g)
                continue
            it = _file_item(p, None, folder)
            if not it:
                continue
            real = _strip_partial(p)
            ext = real.suffix.lower()
            wanted = (it.kind in ("movie", "episode", "music", "rom", "installer")
                      or ext in (".exe", ".appimage", ".iso", ".chd", ".cue"))
            if it.kind == "music" and it.size < 512 * 1024:
                wanted = False
            if wanted:
                it.category = kinds.CATEGORY_FOR_KIND[it.kind]
                out.append(it)
    out.sort(key=lambda i: i.mtime, reverse=True)
    return out
