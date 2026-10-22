"""Finding and downloading the programs Bramble carries, from more than one source.

Nothing here runs on its own. The window calls `latest()` only when a carried
program could not open something (or when asked on the PROGRAMS page), shows
what it found, and calls `install()` only after the person says yes. The build
(tools/fetch-tools.py) uses the same code to fill the drive.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths

UA = {"User-Agent": "Bramble/1.0 (+media manager)"}


@dataclass
class Release:
    tool: str
    os: str
    version: str
    url: str
    filename: str
    source: str              # human name of where it comes from
    sha_url: str = ""        # a checksum file, when the source publishes one
    size: int = 0


def _get(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _gh_latest(repo: str) -> dict:
    return json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest"))


def _gh_asset(rel: dict, pattern: str) -> tuple[str, str] | None:
    for a in rel.get("assets", []):
        if re.search(pattern, a["name"]):
            return a["browser_download_url"], a["name"]
    return None


def _vkey(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v))


# --- sources: each returns a Release or raises -----------------------------------

def _vlc_videolan(base: str, name: str) -> Callable[[str], Release]:
    def f(os_key: str) -> Release:
        if os_key != "windows":
            raise LookupError("VLC carries a Windows copy only; Linux uses mpv or the PC's VLC")
        html = _get(base)
        vers = sorted(set(re.findall(r"vlc-(\d+\.\d+\.\d+(?:\.\d+)?)-win64\.zip", html)), key=_vkey)
        if not vers:
            raise LookupError("no VLC build listed")
        v = vers[-1]
        fn = f"vlc-{v}-win64.zip"
        return Release("vlc", os_key, v, base + fn, fn, name, sha_url=base + fn + ".sha256")
    return f


def _mpv_win(repo: str) -> Callable[[str], Release]:
    def f(os_key: str) -> Release:
        if os_key == "linux":
            rel = _gh_latest("pkgforge-dev/mpv-AppImage")
            hit = _gh_asset(rel, r"x86_64\.AppImage$")
            if not hit:
                raise LookupError("no x86_64 AppImage")
            v = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", rel["tag_name"]).group(1)
            return Release("mpv", os_key, v, hit[0], hit[1], "github.com/pkgforge-dev")
        rel = _gh_latest(repo)
        hit = _gh_asset(rel, r"^mpv-x86_64-\d{8}-git-[0-9a-f]+\.7z$")
        if not hit:
            raise LookupError("no mpv build")
        return Release("mpv", os_key, rel["tag_name"][:10], hit[0], hit[1], f"github.com/{repo}")
    return f


def _retroarch(os_key: str) -> Release:
    html = _get("https://buildbot.libretro.com/stable/")
    vers = sorted(set(re.findall(r'/stable/(\d+\.\d+\.\d+)/', html)), key=_vkey)
    if not vers:
        raise LookupError("no stable RetroArch listed")
    v = vers[-1]
    sub = "windows/x86_64" if os_key == "windows" else "linux/x86_64"
    url = f"https://buildbot.libretro.com/stable/{v}/{sub}/RetroArch.7z"
    return Release("retroarch", os_key, v, url, f"RetroArch-{os_key}-{v}.7z", "buildbot.libretro.com")


def _retroarch_nightly(os_key: str) -> Release:
    sub = "windows/x86_64" if os_key == "windows" else "linux/x86_64"
    url = f"https://buildbot.libretro.com/nightly/{sub}/RetroArch.7z"
    return Release("retroarch", os_key, "nightly-" + datetime.date.today().isoformat(), url,
                   f"RetroArch-{os_key}-nightly.7z", "buildbot.libretro.com (nightly)")


def _proton(os_key: str) -> Release:
    if os_key != "linux":
        raise LookupError("Proton is for Linux only")
    rel = _gh_latest("GloriousEggroll/proton-ge-custom")
    hit = _gh_asset(rel, r"^GE-Proton[\d-]+(-x86_64)?\.tar\.gz$")
    sha = _gh_asset(rel, r"^GE-Proton[\d-]+(-x86_64)?\.sha512sum$")
    if not hit:
        raise LookupError("no GE-Proton tarball")
    return Release("proton", os_key, rel["tag_name"], hit[0], hit[1],
                   "github.com/GloriousEggroll", sha_url=sha[0] if sha else "")


def _sevenzip_github(os_key: str) -> Release:
    rel = _gh_latest("ip7z/7zip")
    pat = r"^7z\d+-linux-x64\.tar\.xz$" if os_key == "linux" else r"^7z\d+-extra\.7z$"
    hit = _gh_asset(rel, pat)
    if not hit:
        raise LookupError("no 7-Zip build")
    return Release("sevenzip", os_key, rel["tag_name"], hit[0], hit[1], "github.com/ip7z")


def _sevenzip_site(os_key: str) -> Release:
    html = _get("https://www.7-zip.org/download.html")
    pat = r"a/(7z(\d+)-linux-x64\.tar\.xz)" if os_key == "linux" else r"a/(7z(\d+)-extra\.7z)"
    hits = sorted(re.findall(pat, html), key=lambda h: int(h[1]))
    if not hits:
        raise LookupError("no 7-Zip build listed")
    fn, num = hits[-1]
    return Release("sevenzip", os_key, f"{num[:2]}.{num[2:]}", f"https://www.7-zip.org/a/{fn}", fn,
                   "7-zip.org")


def _ffmpeg_btbn(os_key: str) -> Release:
    rel = _gh_latest("BtbN/FFmpeg-Builds")
    pat = r"^ffmpeg-master-latest-linux64-gpl\.tar\.xz$" if os_key == "linux" else \
        r"^ffmpeg-master-latest-win64-gpl\.zip$"
    hit = _gh_asset(rel, pat)
    if not hit:
        raise LookupError("no ffmpeg build")
    return Release("ffprobe", os_key, rel.get("published_at", "")[:10] or rel["tag_name"],
                   hit[0], hit[1], "github.com/BtbN")


def _ffmpeg_alt(os_key: str) -> Release:
    if os_key == "linux":
        return Release("ffprobe", os_key, "release",
                       "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
                       "ffmpeg-release-amd64-static.tar.xz", "johnvansickle.com")
    return Release("ffprobe", os_key, "release",
                   "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                   "ffmpeg-release-essentials.zip", "gyan.dev")


def _aria2_official(os_key: str) -> Release:
    if os_key != "windows":
        raise LookupError("the official aria2 release has no Linux build")
    rel = _gh_latest("aria2/aria2")
    hit = _gh_asset(rel, r"win-64bit-build\d+\.zip$")
    if not hit:
        raise LookupError("no Windows aria2 build")
    return Release("aria2", os_key, rel["tag_name"].replace("release-", ""), hit[0], hit[1],
                   "github.com/aria2")


def _aria2_static(os_key: str) -> Release:
    rel = _gh_latest("abcfy2/aria2-static-build")
    pat = r"x86_64-linux-musl_static\.zip$" if os_key == "linux" else r"x86_64-w64-mingw32_static\.zip$"
    hit = _gh_asset(rel, pat)
    if not hit:
        raise LookupError("no static aria2 build")
    return Release("aria2", os_key, rel["tag_name"], hit[0], hit[1], "github.com/abcfy2")


SOURCES: dict[str, list[Callable[[str], Release]]] = {
    "aria2": [_aria2_official, _aria2_static],
    "vlc": [_vlc_videolan("https://get.videolan.org/vlc/last/win64/", "get.videolan.org"),
            _vlc_videolan("https://download.videolan.org/pub/videolan/vlc/last/win64/",
                          "download.videolan.org"),
            _vlc_videolan("https://mirror.csclub.uwaterloo.ca/vlc/vlc/last/win64/",
                          "mirror.csclub.uwaterloo.ca")],
    "mpv": [_mpv_win("shinchiro/mpv-winbuild-cmake"), _mpv_win("zhongfly/mpv-winbuild")],
    "retroarch": [_retroarch, _retroarch_nightly],
    "proton": [_proton],
    "sevenzip": [_sevenzip_github, _sevenzip_site],
    "ffprobe": [_ffmpeg_btbn, _ffmpeg_alt],
}

# Cores fetched with RetroArch, one per common console (kinds.SYSTEMS order).
CORES = ["mesen", "nestopia", "snes9x", "mupen64plus_next", "gambatte", "mgba", "melonds",
         "genesis_plus_gx", "picodrive", "swanstation", "pcsx_rearmed", "ppsspp",
         "mednafen_pce_fast", "stella", "fbneo"]


def latest(tool_id: str, os_key: str = paths.OS_KEY) -> tuple[Release | None, list[str]]:
    """The newest release across all sources, and what went wrong with the others."""
    best: Release | None = None
    errors: list[str] = []
    for src in SOURCES.get(tool_id, []):
        try:
            rel = src(os_key)
        except Exception as e:   # network, parsing, rate limits: try the next source
            errors.append(f"{getattr(src, '__name__', 'source')}: {e}")
            continue
        if best is None or (_vkey(rel.version) > _vkey(best.version)
                            and not rel.version.startswith("nightly")):
            best = rel
        if tool_id in ("vlc", "proton"):
            break                # the first answer is authoritative; others are mirrors
    if best and not best.size:
        best.size = remote_size(best.url)
    return best, errors


def remote_size(url: str) -> int:
    try:
        req = urllib.request.Request(url, method="HEAD", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return 0


# --- downloading and putting in place ---------------------------------------------

def download(url: str, dest: Path, progress: Callable[[int, int], None] | None = None,
             mirrors: list[str] = ()) -> Path:
    last_err = None
    for u in [url, *mirrors]:
        try:
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            return dest
        except Exception as e:
            last_err = e
    raise OSError(f"download failed: {last_err}")


def _verify(rel: Release, file: Path) -> None:
    if not rel.sha_url:
        return
    try:
        text = _get(rel.sha_url)
    except Exception:
        return                    # the checksum file is optional; the download is still used
    want = re.search(r"\b([0-9a-f]{64}|[0-9a-f]{128})\b", text)
    if not want:
        return
    algo = "sha256" if len(want.group(1)) == 64 else "sha512"
    h = hashlib.new(algo)
    with open(file, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != want.group(1):
        raise OSError(f"{file.name} does not match its published checksum; not used.")


def _seven_zip() -> list[str]:
    from . import tools
    for found in tools.find_all("sevenzip"):
        try:
            return tools.localize(found).argv
        except OSError:
            continue
    for c in ("7zz", "7z", "7za", "7zr"):
        w = shutil.which(c)
        if w:
            return [w]
    raise OSError("7-Zip is needed to unpack this download and was not found.")


def _extract(archive: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    elif re.search(r"\.tar(\.(gz|xz|bz2|zst))?$|\.tgz$", name):
        with tarfile.open(archive) as t:
            t.extractall(into, filter="tar")
    elif name.endswith(".7z"):
        r = subprocess.run(_seven_zip() + ["x", "-y", f"-o{into}", str(archive)],
                           capture_output=True, text=True)
        if r.returncode:
            raise OSError(f"7-Zip could not unpack {archive.name}: {r.stderr.strip()[-200:]}")
    else:
        raise OSError(f"Do not know how to unpack {archive.name}")


def _move_contents(src: Path, dest: Path) -> None:
    """Replace dest with src's contents (only inside Bramble's own tools folder)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


def install(rel: Release, tools_root: Path, progress: Callable[[str], None] | None = None,
            bar: Callable[[int, int], None] | None = None) -> str:
    """Download `rel` and put it where tools.py looks for it under tools_root
    (…/tools/<os>). Returns a one-line summary."""
    say = progress or (lambda s: None)
    tools_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bramble-") as td:
        tmp = Path(td)
        file = tmp / rel.filename
        say(f"Downloading {rel.filename} from {rel.source}…")
        download(rel.url, file, bar)
        _verify(rel, file)
        say("Unpacking…")
        out = tmp / "out"
        t, o = rel.tool, rel.os
        if t == "vlc":
            _extract(file, out)
            inner = next(p for p in out.iterdir() if p.is_dir())
            _move_contents(inner, tools_root / "vlc")
        elif t == "mpv" and o == "linux":
            (tools_root / "mpv").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, tools_root / "mpv" / "mpv.AppImage")
        elif t == "mpv":
            _extract(file, out)
            _move_contents(out, tools_root / "mpv")
        elif t == "retroarch":
            _extract(file, out)
            if o == "windows":
                inner = next(p for p in out.iterdir() if p.is_dir())
                cores = tools_root / "retroarch" / "cores"
                keep = tmp / "cores"
                if cores.exists():
                    shutil.move(str(cores), str(keep))
                _move_contents(inner, tools_root / "retroarch")
                if keep.exists():
                    (tools_root / "retroarch" / "cores").mkdir(exist_ok=True)
                    for p in keep.iterdir():
                        shutil.move(str(p), str(tools_root / "retroarch" / "cores" / p.name))
            else:
                app = next(out.rglob("*.AppImage"))
                (tools_root / "retroarch").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(app, tools_root / "retroarch" / "RetroArch.AppImage")
            say("Fetching emulator cores…")
            fetch_cores(o, tools_root / "retroarch" / "cores", say)
        elif t == "proton":
            (tools_root / "proton").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, tools_root / "proton" / "GE-Proton.tar.gz")
        elif t == "sevenzip":
            dest = tools_root / "7zip"
            dest.mkdir(parents=True, exist_ok=True)
            if o == "linux":
                _extract(file, out)
                shutil.copyfile(next(out.rglob("7zz")), dest / "7zz")
            else:
                download("https://www.7-zip.org/a/7zr.exe", dest / "7zr.exe")
                _extract(file, out)
                shutil.copyfile(next(out.rglob("7za.exe")), dest / "7za.exe")
        elif t == "ffprobe":
            # one download carries both: ffprobe looks inside files, ffmpeg makes thumbnails
            _extract(file, out)
            dest = tools_root / "ffmpeg"
            dest.mkdir(parents=True, exist_ok=True)
            for name in ("ffprobe", "ffmpeg"):
                exe = name + (".exe" if o == "windows" else "")
                shutil.copyfile(next(p for p in out.rglob(exe) if p.is_file()), dest / exe)
        elif t == "aria2":
            _extract(file, out)
            exe = "aria2c.exe" if o == "windows" else "aria2c"
            dest = tools_root / "aria2"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(next(p for p in out.rglob(exe) if p.is_file()), dest / exe)
        else:
            raise OSError(f"Do not know where {t} goes")
    _record(tools_root, rel)
    return f"{rel.tool} {rel.version} from {rel.source}"


def fetch_cores(os_key: str, dest: Path, say=lambda s: None, names: list[str] = CORES) -> list[str]:
    sub = "windows/x86_64" if os_key == "windows" else "linux/x86_64"
    ext = ".dll" if os_key == "windows" else ".so"
    dest.mkdir(parents=True, exist_ok=True)
    missing = []
    for core in names:
        target = dest / f"{core}_libretro{ext}"
        url = f"https://buildbot.libretro.com/nightly/{sub}/latest/{core}_libretro{ext}.zip"
        try:
            with tempfile.TemporaryDirectory() as td:
                z = Path(td) / "c.zip"
                download(url, z)
                with zipfile.ZipFile(z) as zf:
                    zf.extract(f"{core}_libretro{ext}", td)
                shutil.copyfile(Path(td) / f"{core}_libretro{ext}", target)
            say(f"core {core}")
        except Exception as e:
            missing.append(f"{core}: {e}")
    return missing


def _record(tools_root: Path, rel: Release) -> None:
    info_file = tools_root.parent / "tools.json"
    try:
        info = json.loads(info_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    info.setdefault(rel.os, {})[rel.tool] = {
        "version": rel.version, "source": rel.source, "file": rel.filename,
        "fetched": datetime.datetime.now().isoformat(timespec="minutes")}
    info_file.write_text(json.dumps(info, indent=2), encoding="utf-8")


def carried_version(tool_id: str, os_key: str = paths.OS_KEY) -> str:
    from . import tools
    return tools.carried_info().get(os_key, {}).get(tool_id, {}).get("version", "")


def is_newer(available: str, have: str) -> bool:
    if not have:
        return True
    if available.startswith("nightly") or have.startswith("nightly"):
        return False
    return _vkey(available) > _vkey(have)
