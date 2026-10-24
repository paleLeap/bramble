"""Where Bramble lives, where the library is, where the carried programs are.

Two ways to run:
  * from the Hawthorn SSD: the code sits in <drive>/LIGAMENTS/bramble, the
    library in <drive>/LIGAMENTS/MARROW, carried programs in
    <drive>/INNARDS/bramble/tools/<linux|windows>.
  * installed on a PC (through Hawthorn): the code sits in the folder the user
    picked; the library defaults to ~/MARROW, and a plugged-in Hawthorn
    drive's MARROW and carried programs are used too whenever it is present.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
OS_KEY = "windows" if IS_WINDOWS else "linux"
ARCH = platform.machine().lower()

PACKAGE_DIR = Path(__file__).resolve().parent
APP_DIR = PACKAGE_DIR.parent
if getattr(sys, "frozen", False):
    # a packaged download: the program's own folder (on the drive, or wherever it was
    # saved), not the temporary one its files unpack into
    APP_DIR = Path(sys.executable).resolve().parent

# The library's folders, in the order the window lists them.
# None built in (user, 2026-10-22): a fresh Bramble shows only its name and "+". Every
# folder in MARROW is a category, named whatever the person called it.
CATEGORIES: list[str] = []
MARROW_NAME = "MARROW"


def _home() -> Path:
    return Path.home()


def config_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))
        return base / "Bramble"
    return Path(os.environ.get("XDG_CONFIG_HOME", _home() / ".config")) / "bramble"


def cache_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local"))
        return base / "Bramble" / "cache"
    return Path(os.environ.get("XDG_CACHE_HOME", _home() / ".cache")) / "bramble"


def data_dir() -> Path:
    """Per-PC state that is bigger than config: the Wine prefix, unpacked programs."""
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local"))
        return base / "Bramble"
    return Path(os.environ.get("XDG_DATA_HOME", _home() / ".local" / "share")) / "bramble"


def is_drive_root(p: Path) -> bool:
    return (p / "INNARDS").is_dir() and (p / "LIGAMENTS").is_dir()


def own_drive() -> Path | None:
    """The Hawthorn drive Bramble is running from, if it is."""
    for parent in APP_DIR.parents:
        if is_drive_root(parent):
            return parent
    return None


def _mount_candidates() -> list[Path]:
    if IS_WINDOWS:
        import string
        return [Path(f"{d}:\\") for d in string.ascii_uppercase
                if d not in "AB" and os.path.exists(f"{d}:\\")]
    out: list[Path] = []
    user = os.environ.get("USER", "")
    for base in (Path("/media") / user, Path("/run/media") / user, Path("/media"), Path("/mnt")):
        try:
            out.extend(p for p in base.iterdir() if p.is_dir())
        except OSError:
            pass
    return out


def find_drives() -> list[Path]:
    """Every plugged-in Hawthorn drive (own one first)."""
    found: list[Path] = []
    mine = own_drive()
    if mine:
        found.append(mine)
    for cand in _mount_candidates():
        try:
            if cand not in found and is_drive_root(cand):
                found.append(cand)
        except OSError:
            continue
    return found


def drive_marrow(drive: Path) -> Path:
    return drive / "LIGAMENTS" / MARROW_NAME


def drive_tools(drive: Path) -> Path:
    return drive / "INNARDS" / "bramble" / "tools" / OS_KEY


def local_marrow() -> Path:
    return _home() / MARROW_NAME


def local_tools() -> Path:
    return data_dir() / "tools" / OS_KEY


def downloads_dir() -> Path:
    if IS_LINUX:
        try:
            import subprocess
            out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True,
                                 text=True, timeout=2).stdout.strip()
            if out:
                return Path(out)
        except (OSError, subprocess.SubprocessError):
            pass
    return _home() / "Downloads"


def ensure_library(root: Path) -> None:
    """Make the category folders under a MARROW root (only adds, never removes)."""
    for name in CATEGORIES:
        (root / name).mkdir(parents=True, exist_ok=True)
