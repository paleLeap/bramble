"""What a file is, and what a person would call it.

Kinds:  movie, episode, music, rom, game_windows, game_linux, program,
        installer, image, document, archive, other
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

VIDEO = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".webm", ".wmv", ".flv", ".mpg",
         ".mpeg", ".ts", ".m2ts", ".vob", ".ogv", ".3gp", ".divx", ".rmvb"}
AUDIO = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".alac",
         ".aiff", ".ape", ".mka"}
IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".heic", ".avif"}
DOCUMENT = {".pdf", ".epub", ".mobi", ".cbz", ".cbr", ".txt", ".md", ".doc", ".docx",
            ".odt", ".rtf", ".xls", ".xlsx", ".ods", ".ppt", ".pptx"}
ARCHIVE = {".zip", ".7z", ".rar", ".tar", ".gz", ".xz", ".bz2", ".zst", ".tgz"}
SUBTITLE = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}
WINDOWS_RUN = {".exe", ".bat", ".cmd", ".lnk"}
WINDOWS_INSTALL = {".msi"}
LINUX_RUN = {".appimage", ".sh", ".x86_64", ".x86", ".run"}
LINUX_INSTALL = {".deb", ".rpm", ".flatpakref"}

# Retro systems: name, RetroArch cores in order of preference, file extensions,
# and the BIOS files the core cannot run without (any one of a group).
@dataclass(frozen=True)
class System:
    key: str
    name: str
    cores: tuple[str, ...]
    exts: tuple[str, ...]
    bios: tuple[tuple[str, ...], ...] = ()
    folder_words: tuple[str, ...] = ()


SYSTEMS: list[System] = [
    System("nes", "NES", ("mesen", "nestopia", "fceumm"), (".nes", ".fds", ".unf"),
           folder_words=("nes", "nintendo entertainment system", "famicom")),
    System("snes", "SNES", ("snes9x", "bsnes"), (".sfc", ".smc", ".swc", ".fig"),
           folder_words=("snes", "super nintendo", "super famicom")),
    System("n64", "Nintendo 64", ("mupen64plus_next", "parallel_n64"), (".n64", ".z64", ".v64"),
           folder_words=("n64", "nintendo 64")),
    System("gb", "Game Boy", ("gambatte", "sameboy", "mgba"), (".gb",),
           folder_words=("game boy", "gameboy", "gb")),
    System("gbc", "Game Boy Color", ("gambatte", "sameboy", "mgba"), (".gbc",),
           folder_words=("game boy color", "gbc")),
    System("gba", "Game Boy Advance", ("mgba", "vba_next"), (".gba",),
           folder_words=("game boy advance", "gba")),
    System("nds", "Nintendo DS", ("melonds", "desmume"), (".nds",),
           folder_words=("nintendo ds", "nds", "ds")),
    System("genesis", "Genesis / Mega Drive", ("genesis_plus_gx", "picodrive"),
           (".md", ".gen", ".smd", ".bin"),
           folder_words=("genesis", "mega drive", "megadrive", "sega genesis")),
    System("sms", "Master System", ("genesis_plus_gx", "picodrive"), (".sms",),
           folder_words=("master system", "sms")),
    System("gg", "Game Gear", ("genesis_plus_gx",), (".gg",), folder_words=("game gear", "gamegear")),
    System("psx", "PlayStation", ("swanstation", "mednafen_psx_hw", "pcsx_rearmed"),
           (".cue", ".chd", ".pbp", ".m3u", ".ccd"),
           bios=(("scph5501.bin", "scph5500.bin", "scph5502.bin", "scph1001.bin",
                  "scph7001.bin", "ps-22a.bin"),),
           folder_words=("playstation", "psx", "ps1", "psone")),
    System("psp", "PSP", ("ppsspp",), (".cso", ".pbp"), folder_words=("psp",)),
    System("pce", "PC Engine / TurboGrafx", ("mednafen_pce_fast",), (".pce",),
           folder_words=("pc engine", "turbografx", "pce")),
    System("atari2600", "Atari 2600", ("stella",), (".a26",), folder_words=("atari 2600", "2600")),
    System("arcade", "Arcade", ("fbneo", "mame2003_plus"), (),
           folder_words=("arcade", "mame", "fbneo", "neo geo", "neogeo")),
]
SYSTEM_BY_KEY = {s.key: s for s in SYSTEMS}
# Extensions that only one system uses, so the file alone says what it is.
_UNIQUE_EXT: dict[str, System] = {}
for _s in SYSTEMS:
    for _e in _s.exts:
        if _e in (".bin", ".pbp"):
            continue
        _UNIQUE_EXT.setdefault(_e, _s)


def system_for(path: Path) -> System | None:
    """Which retro system a file belongs to, from its extension or its folders."""
    ext = path.suffix.lower()
    words = " / ".join(p.lower() for p in path.parts[-4:-1])
    # A folder named for a system wins: Video Games/SNES/game.zip
    for s in sorted(SYSTEMS, key=lambda s: -max((len(w) for w in s.folder_words), default=0)):
        for w in s.folder_words:
            if re.search(rf"(^|[ /_\-\[(]){re.escape(w)}($|[ /_\-\])])", words):
                if ext in s.exts or ext in ARCHIVE or ext in (".iso", ".chd", ".cue", ".bin"):
                    return s
    return _UNIQUE_EXT.get(ext)


EPISODE_RE = re.compile(r"(?i)\bS(\d{1,2})[ ._-]?E(\d{1,3})\b|\b(\d{1,2})x(\d{2,3})\b")
TAGS = re.compile(r"(?i)\b(2160p|1080p|720p|576p|480p|4k|uhd|hdr|hdr10|dv|web-?rip|web-?dl|"
                  r"webrip|bluray|blu-ray|brrip|bdrip|hdrip|dvdrip|hdtv|x26[45]|h\.?26[45]|"
                  r"hevc|avc|10.?bit|ddp?(?:5\.1|2\.0)?|aac|ac3|eac3|dts|truehd|atmos|remux|"
                  r"proper|repack|extended|unrated|imax|yts|yify|rarbg|amzn|nf|dsnp|hmax)\b")


def _tidy(name: str) -> str:
    name = re.sub(r"[._]+", " ", name)
    name = re.sub(r"\[[^\]]*\]|\{[^}]*\}", " ", name)
    return re.sub(r"\s+", " ", name).strip(" -")


def nice_title(path: Path) -> tuple[str, str | None]:
    """('Hokum', '2026') from Hokum.2026.1080p.WEBRip...-NeoNoir.mkv."""
    name = _tidy(path.stem)
    m = re.search(r"[( ]((?:19|20)\d\d)(?:[) ]|$)", name)
    year = None
    if m and m.start() > 0:
        year = m.group(1)
        name = name[:m.start()]
    else:
        t = TAGS.search(name)
        if t and t.start() > 0:
            name = name[:t.start()]
    name = re.sub(r"\([^)]*\)", "", name).strip(" -")
    return (name or path.stem), year


@dataclass
class Episode:
    show: str
    season: int
    number: int
    title: str = ""


def episode_info(path: Path) -> Episode | None:
    m = EPISODE_RE.search(path.stem)
    if not m:
        return None
    season = int(m.group(1) or m.group(3))
    number = int(m.group(2) or m.group(4))
    before = _tidy(path.stem[:m.start()])
    before = re.sub(r"[( ]((?:19|20)\d\d)[) ]?$", "", before).strip(" -")
    after = _tidy(path.stem[m.end():])
    t = TAGS.search(after)
    if t:
        after = after[:t.start()]
    show = before
    if not show:
        # "Show Name/Season 1/S01E02.mkv": take the show from the folders.
        for part in reversed(path.parts[:-1]):
            if not re.match(r"(?i)^(season|series|s)\s*\d+$", part):
                show = _tidy(part)
                break
    return Episode(show or "Unknown show", season, number, after.strip(" -"))


def _is_elf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


SKIP_EXE = re.compile(r"(?i)^(unins\d*|uninstall|setup|install|vc_?redist.*|dxsetup|dxwebsetup|"
                      r"unitycrashhandler(32|64)?|crashreport.*|crashpad_handler|"
                      r"ue4prereqsetup.*|dotnet.*|physx.*|oalinst|vcredist.*|"
                      r"quicksfv|notification_helper|easyanticheat_setup)$")


def main_executable(folder: Path) -> Path | None:
    """The .exe most likely to start a game folder: not an uninstaller or redist,
    nearest the top, biggest."""
    best: tuple[int, int, Path] | None = None
    try:
        for p in folder.rglob("*"):
            if p.suffix.lower() != ".exe" or SKIP_EXE.match(p.stem):
                continue
            rel_depth = len(p.relative_to(folder).parts)
            if rel_depth > 4 or any(x.lower() in ("_redist", "redist", "_commonredist",
                                                   "directx", "support") for x in p.parts):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            key = (rel_depth, -size)
            if best is None or key < best[:2]:
                best = (rel_depth, -size, p)
    except OSError:
        return None
    return best[2] if best else None


def main_linux_executable(folder: Path) -> Path | None:
    cands = []
    try:
        for p in folder.iterdir():
            low = p.name.lower()
            if p.is_file() and (low.endswith((".appimage", ".x86_64", ".sh", ".x86")) or
                                (not p.suffix and _is_elf(p))):
                cands.append(p)
    except OSError:
        return None
    if not cands:
        return None
    pri = lambda p: (0 if p.name.lower().endswith((".x86_64", ".appimage")) else
                     1 if not p.suffix else 2, -p.stat().st_size)
    return sorted(cands, key=pri)[0]


def classify(path: Path, category: str | None = None) -> str:
    """The kind of a single file. `category` is the library folder it sits in."""
    ext = path.suffix.lower()
    in_games = category == "Video Games"
    if ext in VIDEO:
        if category == "TV Shows" or EPISODE_RE.search(path.stem):
            return "episode"
        return "movie"
    if ext in AUDIO:
        return "music"
    if in_games or category is None:
        sysm = system_for(path)
        if sysm and (in_games or ext in _UNIQUE_EXT):
            return "rom"
    if ext in WINDOWS_RUN:
        return "game_windows" if in_games else "program"
    if ext in WINDOWS_INSTALL or ext in LINUX_INSTALL:
        return "installer"
    if ext in LINUX_RUN or (not ext and _is_elf(path)):
        return "game_linux" if in_games else "program"
    if ext in IMAGE:
        return "image"
    if ext in DOCUMENT:
        return "document"
    if ext in ARCHIVE:
        return "archive"
    return "other"


# Where a newly arrived file should be filed, by kind.
CATEGORY_FOR_KIND = {
    "movie": "Movies", "episode": "TV Shows", "music": "Music",
    "rom": "Video Games", "game_windows": "Video Games", "game_linux": "Video Games",
    "program": "Programs", "installer": "Programs",
    "image": "Other", "document": "Other", "archive": "Other", "other": "Other",
}

KIND_LABEL = {
    "movie": "Movie", "episode": "TV episode", "music": "Music", "rom": "Retro game",
    "game_windows": "Windows game", "game_linux": "Linux game", "program": "Program",
    "installer": "Installer", "image": "Picture", "document": "Document",
    "archive": "Archive", "other": "File",
}


def suggested_subfolder(path: Path, kind: str) -> list[str]:
    """Folders under the category to suggest: TV Shows/<Show>/Season N, Video Games/<System>."""
    if kind == "episode":
        ep = episode_info(path)
        if ep:
            return [ep.show, f"Season {ep.season}"]
    if kind == "rom":
        s = system_for(path)
        if s:
            return [s.name.replace(" / ", " - ")]
    if kind == "game_windows":
        return ["PC"]
    if kind == "game_linux":
        return ["Linux"]
    return []
