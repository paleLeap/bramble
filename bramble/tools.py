"""The programs Bramble opens things with: where to find them on this PC, where
the drive carries them, and how to make a carried one runnable here.

On Linux nothing on the exFAT drive can be executed in place (no exec bit,
no symlinks), so a carried program is "localized" on first use: copied or
unpacked into ~/.local/share/bramble/tools and run from there. Windows runs
carried programs straight from the drive.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import paths


@dataclass
class Tool:
    id: str
    name: str
    purpose: str
    linux_cmds: tuple[str, ...] = ()          # names on PATH
    linux_flatpak: str = ""                   # flatpak app id
    linux_globs: tuple[str, ...] = ()         # absolute globs, ~ expanded
    win_globs: tuple[str, ...] = ()           # %VAR% expanded
    win_cmds: tuple[str, ...] = ()
    carried_linux: str = ""                   # path under tools/linux (file or archive)
    carried_windows: str = ""                 # path under tools/windows
    install_hint_linux: str = ""              # apt package
    install_hint_windows: str = ""            # winget id


TOOLS: dict[str, Tool] = {t.id: t for t in [
    Tool("vlc", "VLC", "Plays almost every film, show and song.",
         linux_cmds=("vlc",), linux_flatpak="org.videolan.VLC",
         linux_globs=("/snap/bin/vlc",),
         win_globs=(r"%ProgramFiles%\VideoLAN\VLC\vlc.exe", r"%ProgramFiles(x86)%\VideoLAN\VLC\vlc.exe"),
         carried_windows="vlc/vlc.exe",
         install_hint_linux="vlc", install_hint_windows="VideoLAN.VLC"),
    Tool("mpv", "mpv", "A second video player: lighter than VLC, very good with new formats.",
         linux_cmds=("mpv",), linux_flatpak="io.mpv.Mpv",
         win_globs=(r"%ProgramFiles%\mpv\mpv.exe", r"%LOCALAPPDATA%\Programs\mpv\mpv.exe"),
         win_cmds=("mpv",),
         carried_linux="mpv/mpv.AppImage", carried_windows="mpv/mpv.exe",
         install_hint_linux="mpv", install_hint_windows="mpv.net"),
    Tool("retroarch", "RetroArch", "Plays retro console games (ROMs) through emulator cores.",
         linux_cmds=("retroarch",), linux_flatpak="org.libretro.RetroArch",
         win_globs=(r"%APPDATA%\RetroArch\retroarch.exe", r"C:\RetroArch-Win64\retroarch.exe",
                    r"%ProgramFiles%\RetroArch\retroarch.exe"),
         carried_linux="retroarch/RetroArch.AppImage", carried_windows="retroarch/retroarch.exe",
         install_hint_linux="retroarch", install_hint_windows="Libretro.RetroArch"),
    Tool("proton", "GE-Proton", "Runs Windows games on Linux (the same setup Bloodborne uses here).",
         linux_globs=("~/.steam/root/compatibilitytools.d/GE-Proton*/files/bin/wine",
                      "~/.local/share/Steam/compatibilitytools.d/GE-Proton*/files/bin/wine",
                      "~/.config/heroic/tools/proton/GE-Proton*/files/bin/wine",
                      "~/.local/share/lutris/runners/wine/*/bin/wine",
                      "/data/Library/Games/*/runners/GE-Proton*/files/bin/wine"),
         carried_linux="proton/GE-Proton.tar.gz"),
    Tool("wine", "Wine", "Runs Windows programs on Linux; the fallback when Proton is missing.",
         linux_cmds=("wine",), install_hint_linux="wine"),
    Tool("sevenzip", "7-Zip", "Opens .zip, .7z, .rar and most other archives.",
         linux_cmds=("7zz", "7z", "7za"),
         win_globs=(r"%ProgramFiles%\7-Zip\7z.exe", r"%ProgramFiles(x86)%\7-Zip\7z.exe"),
         carried_linux="7zip/7zz", carried_windows="7zip/7za.exe",
         install_hint_linux="7zip", install_hint_windows="7zip.7zip"),
    Tool("ffprobe", "ffprobe", "Looks inside video files (sound, subtitles, format) to spot problems early.",
         linux_cmds=("ffprobe",), win_cmds=("ffprobe",),
         carried_linux="ffmpeg/ffprobe", carried_windows="ffmpeg/ffprobe.exe",
         install_hint_linux="ffmpeg", install_hint_windows="Gyan.FFmpeg"),
]}


@dataclass
class Found:
    tool: Tool
    where: str                  # "this PC" or "drive"
    argv: list[str]             # how to start it (before file arguments)
    path: Path | None = None    # the executable (or the carried file before localizing)
    carried: bool = False
    needs_localize: bool = False
    env: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.tool.name} ({self.where})"


def _expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))


def _flatpak_has(app_id: str) -> bool:
    if not app_id or not shutil.which("flatpak"):
        return False
    try:
        r = subprocess.run(["flatpak", "info", app_id], capture_output=True, timeout=4)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def find_on_pc(tool: Tool) -> Found | None:
    if paths.IS_WINDOWS:
        for g in tool.win_globs:
            hits = sorted(glob.glob(_expand(g)))
            if hits:
                return Found(tool, "this PC", [hits[-1]], Path(hits[-1]))
        for c in tool.win_cmds:
            w = shutil.which(c)
            if w:
                return Found(tool, "this PC", [w], Path(w))
        return None
    for c in tool.linux_cmds:
        w = shutil.which(c)
        if w:
            return Found(tool, "this PC", [w], Path(w))
    for g in tool.linux_globs:
        hits = sorted(glob.glob(_expand(g)))
        if hits:
            return Found(tool, "this PC", [hits[-1]], Path(hits[-1]))
    if _flatpak_has(tool.linux_flatpak):
        return Found(tool, "this PC", ["flatpak", "run", tool.linux_flatpak])
    return None


def carried_roots() -> list[Path]:
    roots = [paths.drive_tools(d) for d in paths.find_drives()]
    roots.append(paths.local_tools())        # downloaded into this PC by Bramble
    return [r for r in roots if r.is_dir()]


def find_carried(tool: Tool) -> Found | None:
    rel = tool.carried_windows if paths.IS_WINDOWS else tool.carried_linux
    if not rel:
        return None
    for root in carried_roots():
        p = root / rel
        if not p.exists():
            continue
        where = "drive" if root != paths.local_tools() else "downloaded"
        if paths.IS_WINDOWS:
            return Found(tool, where, [str(p)], p, carried=True)
        return Found(tool, where, [], p, carried=True, needs_localize=True)
    return None


def find_all(tool_id: str) -> list[Found]:
    tool = TOOLS[tool_id]
    out = [f for f in (find_on_pc(tool), find_carried(tool)) if f]
    return out


def carried_info() -> dict:
    """tools.json written by the fetcher: versions of what the drive carries."""
    for root in carried_roots():
        try:
            return json.loads((root.parent / "tools.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


# --- making a carried program runnable on Linux ---------------------------------

def _stamp(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p.name}:{st.st_size}:{int(st.st_mtime)}".encode()).hexdigest()[:10]


def _make_exec(p: Path) -> None:
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _has_fuse2() -> bool:
    for d in ("/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib"):
        if glob.glob(f"{d}/libfuse.so.2*"):
            return True
    return False


def localize(found: Found, progress=None) -> Found:
    """Copy or unpack a carried program into this PC's tools folder (once) and
    return a Found that can be executed. Raises OSError with a plain reason."""
    if not found.needs_localize or found.path is None:
        return found
    src = found.path
    dest_root = paths.data_dir() / "localized" / f"{found.tool.id}-{_stamp(src)}"
    marker = dest_root / ".ready"
    if not marker.exists():
        if progress:
            progress(f"Preparing {found.tool.name} from the drive (first time on this PC)…")
        if dest_root.exists():
            shutil.rmtree(dest_root, ignore_errors=True)
        dest_root.mkdir(parents=True)
        name = src.name.lower()
        if name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.zst", ".tar")):
            with tarfile.open(src) as tf:
                tf.extractall(dest_root, filter="tar")
        elif name.endswith(".zip"):
            with zipfile.ZipFile(src) as zf:
                zf.extractall(dest_root)
        elif name.endswith(".appimage"):
            local = dest_root / src.name
            shutil.copy2(src, local)
            _make_exec(local)
            if not _has_fuse2():
                # No FUSE: unpack the AppImage once instead of mounting it.
                subprocess.run([str(local), "--appimage-extract"], cwd=dest_root,
                               capture_output=True, timeout=600)
        else:
            # A folder (copy it all) or a single program file.
            if src.is_dir():
                shutil.copytree(src, dest_root / src.name, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest_root / src.name)
        for p in dest_root.rglob("*"):
            if p.is_file() and (p.suffix in ("", ".AppImage", ".so", ".sh") or "bin" in p.parts):
                try:
                    _make_exec(p)
                except OSError:
                    pass
        marker.write_text("ok")
    exe = _localized_exe(found.tool.id, dest_root, src)
    if exe is None:
        raise OSError(f"{found.tool.name} on the drive looks incomplete ({src.name}).")
    env = {}
    if found.tool.id == "proton":
        env["PATH"] = f"{exe.parent}{os.pathsep}{os.environ.get('PATH', '')}"
    return Found(found.tool, found.where, [str(exe)], exe, carried=True, env=env)


def _localized_exe(tool_id: str, root: Path, src: Path) -> Path | None:
    if tool_id == "proton":
        hits = sorted(root.glob("*/files/bin/wine"))
        return hits[-1] if hits else None
    if src.name.lower().endswith(".appimage"):
        apprun = root / "squashfs-root" / "AppRun"
        if apprun.exists():
            return apprun
        return root / src.name
    direct = root / src.name
    if direct.is_file():
        return direct
    hits = [p for p in root.rglob(src.name) if p.is_file()]
    return hits[0] if hits else None


def retroarch_core_dirs(retroarch: Found | None) -> list[Path]:
    dirs: list[Path] = []
    for root in carried_roots():
        dirs.append(root / "retroarch" / "cores")
    if paths.IS_WINDOWS:
        if retroarch and retroarch.path:
            dirs.insert(0, retroarch.path.parent / "cores")
        dirs.append(Path(_expand(r"%APPDATA%\RetroArch\cores")))
    else:
        dirs[:0] = [Path.home() / ".config/retroarch/cores",
                    Path.home() / ".var/app/org.libretro.RetroArch/config/retroarch/cores",
                    Path("/usr/lib/x86_64-linux-gnu/libretro"), Path("/usr/lib/libretro"),
                    Path("/usr/lib64/libretro")]
    return [d for d in dirs if d.is_dir()]


def find_core(core: str, retroarch: Found | None) -> Path | None:
    ext = ".dll" if paths.IS_WINDOWS else ".so"
    for d in retroarch_core_dirs(retroarch):
        p = d / f"{core}_libretro{ext}"
        if p.exists():
            if not paths.IS_WINDOWS and paths.own_drive() and str(p).startswith(str(paths.own_drive())):
                return _localize_file(p)
            for drive in paths.find_drives():
                if str(p).startswith(str(drive)) and not paths.IS_WINDOWS:
                    return _localize_file(p)
            return p
    return None


def _localize_file(p: Path) -> Path:
    dest = paths.data_dir() / "localized" / "files" / f"{_stamp(p)}-{p.name}"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    return dest
