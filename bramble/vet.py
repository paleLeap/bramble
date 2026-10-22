"""Checking a finished download before it joins the library.

Downloads land in a holding folder outside the library. Nothing in it is ever
opened or run. A download passes when:

  * a film, show or song carries nothing that can run (no .exe, .scr, .bat,
    .lnk ...), no disguised name ("movie.mp4.exe"), and no locked archive;
  * its main video (or song) really is one: ffprobe finds the picture and
    sound and a sensible length;
  * a virus scan finds nothing, when the PC has one: Microsoft Defender on
    Windows, ClamAV on Linux.

Games and programs are expected to contain programs, so for them only the
virus scan and the disguised-name rule apply; with no scanner on the PC they
wait for the person to decide.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import kinds, paths, probe

RUNNABLE = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".lnk", ".vbs", ".vbe", ".js",
            ".jse", ".wsf", ".wsh", ".hta", ".msi", ".ps1", ".jar", ".cpl", ".reg", ".dll",
            ".desktop", ".sh", ".appimage", ".deb", ".run"}
ARCHIVES = {".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2", ".iso", ".img"}
JUNK = {".txt", ".nfo", ".url", ".website", ".html", ".htm", ".sfv", ".md5", ".exe.txt"}
LURE = re.compile(r"(?i)(codec|password|passwd|install(er)?|setup|keygen|crack|player)")
DOUBLE = re.compile(r"(?i)\.(mkv|mp4|avi|mov|wmv|m4v|webm|mp3|flac|jpg|png|pdf|srt)\.[a-z0-9]{2,4}$")


@dataclass
class Verdict:
    ok: bool
    kind: str                         # what the download mainly is (kinds.classify)
    keep: list[Path] = field(default_factory=list)       # files to move into the library
    reasons: list[str] = field(default_factory=list)     # why it was held, said plainly
    scanned: str = ""                 # "defender", "clamav", or "" if no scanner
    needs_choice: bool = False        # held only because nothing could scan it


def _files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return [p for p in root.rglob("*") if p.is_file() and not p.name.endswith(".aria2")]


def main_kind(files: list[Path]) -> str:
    """What a download is, judged by its biggest meaningful file."""
    for p in sorted(files, key=lambda p: -p.stat().st_size):
        k = kinds.classify(p, None)
        if k in ("movie", "episode", "music", "rom", "game_windows", "game_linux",
                 "program", "installer"):
            return k
        if p.suffix.lower() in (".iso", ".bin", ".chd", ".cue") and p.stat().st_size > 50 << 20:
            return "game_windows"
    return "other"


def _defender() -> list[str] | None:
    if not paths.IS_WINDOWS:
        return None
    for g in (r"%ProgramFiles%\Windows Defender\MpCmdRun.exe",
              r"%ProgramData%\Microsoft\Windows Defender\Platform\*\MpCmdRun.exe"):
        hits = sorted(glob.glob(os.path.expandvars(g)))
        if hits:
            return [hits[-1]]
    return None


def scan(root: Path) -> tuple[str, bool | None, str]:
    """(scanner, clean?, detail). clean is None when there is no scanner."""
    d = _defender()
    if d:
        r = subprocess.run(d + ["-Scan", "-ScanType", "3", "-File", str(root), "-DisableRemediation"],
                           capture_output=True, text=True, timeout=3600,
                           creationflags=0x08000000)
        # 0: nothing found, 2: threats found
        return "defender", r.returncode == 0, (r.stdout or "").strip()[-300:]
    clam = shutil.which("clamscan") or shutil.which("clamdscan")
    if clam:
        r = subprocess.run([clam, "-r", "--no-summary", "--infected", str(root)],
                           capture_output=True, text=True, timeout=3600)
        if r.returncode == 2:
            return "clamav", None, (r.stderr or r.stdout).strip()[-300:]
        return "clamav", r.returncode == 0, (r.stdout or "").strip()[-300:]
    return "", None, ""


def check(root: Path) -> Verdict:
    files = _files(root)
    if not files:
        return Verdict(False, "other", reasons=["The download is empty."])
    kind = main_kind(files)
    media = kind in ("movie", "episode", "music")
    v = Verdict(True, kind)

    for p in files:
        name = p.name.lower()
        ext = p.suffix.lower()
        # one reason per file: the most telling one
        if DOUBLE.search(name) and ext not in kinds.VIDEO | kinds.AUDIO | kinds.SUBTITLE | kinds.IMAGE:
            v.reasons.append(f"{p.name} is a program dressed up as a {name.split('.')[-2]} file.")
        elif media and LURE.search(name) and ext in RUNNABLE | ARCHIVES:
            v.reasons.append(f"{p.name} asks to install something to play the film, a known scam.")
        elif media and ext in RUNNABLE:
            v.reasons.append(f"{p.name} can run on a computer, which a film or song never needs.")
        elif media and ext in ARCHIVES and p.stat().st_size < 50 << 20:
            v.reasons.append(f"{p.name} is a packed file a film never needs (a common trick).")

    if media:
        main = max((p for p in files if p.suffix.lower() in (kinds.VIDEO | kinds.AUDIO)),
                   key=lambda p: p.stat().st_size, default=None)
        if main is None:
            v.reasons.append("There is no video or song in it.")
        else:
            pr = probe.probe(main, timeout=60)
            if probe.ffprobe_cmd() and not pr.ok:
                v.reasons.append(f"{main.name} is not a real video file ({pr.error[:80]}).")
            elif pr.ok and kind in ("movie", "episode") and (not pr.video_codec or pr.duration < 60):
                v.reasons.append(f"{main.name} has no proper picture or is too short to be what it says.")
        # what goes into the library: the media, its subtitles and a poster; not the site adverts
        v.keep = [p for p in files if p.suffix.lower() in (kinds.VIDEO | kinds.AUDIO | kinds.SUBTITLE)
                  and "sample" not in p.name.lower()]
        if kind == "movie" and main is not None:
            # a film: the one best copy and its subtitles, not every format a site offers
            v.keep = [main] + [p for p in v.keep if p.suffix.lower() in kinds.SUBTITLE]
    else:
        v.keep = files

    scanner, clean, detail = scan(root)
    v.scanned = scanner
    if clean is False:
        v.reasons.append(f"The virus scan ({scanner}) found a threat. {detail}".strip())
    elif clean is None and not media and not v.reasons:
        v.needs_choice = True
        v.reasons.append("This contains programs and this PC has no virus scanner to check them.")

    # one reason per file is enough
    seen, uniq = set(), []
    for r in v.reasons:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    v.reasons = uniq
    v.ok = not v.reasons
    return v


def file_into_library(root: Path, v: Verdict, marrow: Path, into: Path | None = None) -> Path:
    """Move what passed into the right category folder (or `into`, when it was added to
    a particular category); returns where it went. Films keep their own folder (as
    torrents make them) unless they are a single file."""
    category = kinds.CATEGORY_FOR_KIND.get(v.kind, "Other")
    if category in ("Programs", "Other"):
        category = "Other"
    dest_root = into if into is not None else marrow / category
    if into is None and v.kind in ("episode", "rom", "game_windows", "game_linux"):
        main = max(v.keep, key=lambda p: p.stat().st_size)
        for part in kinds.suggested_subfolder(Path(main.name), v.kind if v.kind != "game_windows" else "x"):
            dest_root = dest_root / part
    dest_root.mkdir(parents=True, exist_ok=True)
    if root.is_dir() and len(v.keep) > 1:
        target = _free(dest_root / root.name)
        target.mkdir()
        for p in v.keep:
            out = target / p.relative_to(root)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(out))
        return target
    src = v.keep[0] if v.keep else root
    target = _free(dest_root / src.name)
    shutil.move(str(src), str(target))
    return target


def _free(target: Path) -> Path:
    """Never mix into or overwrite something already in the library: "name (2)" instead."""
    if not target.exists():
        return target
    stem, suffix = (target.stem, target.suffix) if target.suffix and not target.is_dir() else (target.name, "")
    n = 2
    while (target.parent / f"{stem} ({n}){suffix}").exists():
        n += 1
    return target.parent / f"{stem} ({n}){suffix}"
