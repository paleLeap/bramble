"""Small thumbnails for the info view, made once and kept in the cache.

Films and episodes: a frame a third of the way in. Music: the embedded cover.
Games: a cover picture in the game's folder, or one named like the game file.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from . import paths, tools
from .library import Item

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
COVER_WORDS = re.compile(r"(?i)(cover|poster|folder|front|box|header|capsule|banner|logo)")
WIDTH = 224

_ffmpeg: list[str] | None = None


def ffmpeg_cmd() -> list[str] | None:
    global _ffmpeg
    if _ffmpeg is None:
        _ffmpeg = []
        for found in tools.find_all("ffmpeg"):
            try:
                _ffmpeg = tools.localize(found).argv
                break
            except OSError:
                continue
    return _ffmpeg or None


def _cache_path(item: Item) -> Path:
    key = f"{item.path}|{item.size}|{int(item.mtime)}"
    d = paths.cache_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".jpg")


def thumbnail(item: Item, pr=None) -> Path | None:
    out = _cache_path(item)
    if out.exists() and out.stat().st_size > 0:
        return out
    if item.kind in ("movie", "episode"):
        cmd = ffmpeg_cmd()
        if not cmd:
            return None
        at = (pr.duration / 3) if pr is not None and getattr(pr, "duration", 0) else 60
        r = _run(cmd + ["-v", "error", "-ss", f"{at:.1f}", "-i", str(item.path), "-frames:v", "1",
                        "-vf", f"scale={WIDTH}:-2", "-y", str(out)])
        return out if r and out.exists() else None
    if item.kind == "music":
        cmd = ffmpeg_cmd()
        if cmd:
            r = _run(cmd + ["-v", "error", "-i", str(item.path), "-an", "-frames:v", "1",
                            "-vf", f"scale={WIDTH}:-2", "-y", str(out)])
            if r and out.exists():
                return out
        return _cover_near(item.path.parent, out)
    if item.kind in ("rom", "game_windows", "game_linux", "program"):
        base = item.path if item.path.is_dir() else item.path.parent
        same = [item.path.with_suffix(e) for e in IMAGE_EXT] if item.path.is_file() else []
        for s in same:
            if s.exists():
                return _scale(s, out)
        if item.path.is_dir():
            return _cover_near(base, out)
    return None


def _cover_near(folder: Path, out: Path) -> Path | None:
    try:
        imgs = [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT and p.is_file()]
    except OSError:
        return None
    if not imgs:
        return None
    named = [p for p in imgs if COVER_WORDS.search(p.stem)]
    pick = (named or sorted(imgs, key=lambda p: -p.stat().st_size))[0]
    return _scale(pick, out)


def _scale(src: Path, out: Path) -> Path | None:
    try:
        from PyQt6.QtGui import QImage
        img = QImage(str(src))
        if img.isNull():
            return None
        from PyQt6.QtCore import Qt
        img = img.scaledToWidth(WIDTH, Qt.TransformationMode.SmoothTransformation)
        return out if img.save(str(out), "JPG", 85) else None
    except Exception:
        return None


def _run(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
