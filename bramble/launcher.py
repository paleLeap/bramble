"""Opening an item: the ordered list of ways to open it, and trying them in turn.

Fastest first: a program already on this PC, then the drive's carried copy,
then the PC's default app (never a web browser for films or music). A way
"fails" if it cannot start or exits with an error within FAIL_WINDOW seconds;
the next one is tried and every attempt is reported back.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import kinds, paths, probe, system, tools
from .library import Item

FAIL_WINDOW = 4.0


@dataclass
class Way:
    """One way to open an item."""
    label: str                      # "VLC (this PC)"
    tool_id: str                    # "vlc", "default", "direct", "bash", "loader", ...
    build: Callable[[], tuple[list[str], dict, Path | None]] | None = None  # argv, env, cwd
    found: tools.Found | None = None
    available: bool = True
    note: str = ""                  # why it is unavailable, or a caveat


@dataclass
class Attempt:
    way: str
    ok: bool
    detail: str = ""


@dataclass
class Outcome:
    ok: bool
    used: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    failed_tool: str = ""           # the tool id that failed last (for "look for a newer one")


# --- the ways, per kind ------------------------------------------------------------

def _player_args(tool_id: str, item: Item, settings, pr: probe.Probe | None) -> list[str]:
    video = item.kind in ("movie", "episode")
    args: list[str] = []
    sub = probe.pick_subtitle(pr, settings["subtitles"], settings["subtitle_language"]) if (
        pr and pr.ok and video) else None
    sidecar = None
    if video and not sub and settings["subtitles"] != "off" and item.sidecar_subs:
        lang = settings["subtitle_language"][:2]
        sidecar = next((s for s in item.sidecar_subs if f".{lang}" in s.name.lower()
                        or "english" in s.name.lower()), item.sidecar_subs[0])
    if tool_id == "vlc":
        if video and settings["fullscreen_video"]:
            args.append("--fullscreen")
        if sub:
            args.append(f"--sub-track={sub.index}")
        elif sidecar:
            args.append(f"--sub-file={sidecar}")
        if not video:
            args.append("--no-video-title-show")
    elif tool_id == "mpv":
        args.append("--force-window=yes")
        if video and settings["fullscreen_video"]:
            args.append("--fs")
        if sub:
            args.append(f"--sid={sub.index + 1}")
        elif sidecar:
            args.append(f"--sub-file={sidecar}")
        elif video and settings["subtitles"] == "off":
            args.append("--sid=no")
    return args


def _tool_ways(tool_id: str, extra: Callable[[tools.Found], tuple[list[str], dict, Path | None]],
               progress=None) -> list[Way]:
    ways = []
    for found in tools.find_all(tool_id):
        def build(found=found):
            ready = tools.localize(found, progress)
            argv, env, cwd = extra(ready)
            return ready.argv + argv, {**ready.env, **env}, cwd
        ways.append(Way(found.label, tool_id, build, found))
    if not ways:
        t = tools.TOOLS[tool_id]
        ways.append(Way(f"{t.name} (not found)", tool_id, None, None, available=False,
                        note=f"{t.name} is not on this PC or the drive."))
    return ways


def _bios_dir(item: Item) -> Path:
    return item.root / "Video Games" / "BIOS"


def _retroarch_cfg(item: Item) -> Path:
    """A small config RetroArch appends, pointing it at the drive's BIOS folder."""
    cfg = paths.cache_dir() / "retroarch-bramble.cfg"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    bios = _bios_dir(item)
    lines = [f'system_directory = "{bios}"'] if bios.is_dir() else []
    lines.append('video_fullscreen = "true"')
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cfg


def _wine_env(prefix_name: str = "prefix") -> dict:
    prefix = paths.data_dir() / "wine" / prefix_name
    prefix.mkdir(parents=True, exist_ok=True)
    return {"WINEPREFIX": str(prefix), "WINEDEBUG": "-all"}


def ways_for(item: Item, settings, pr: probe.Probe | None = None, progress=None) -> list[Way]:
    k = item.kind
    target = item.target
    ways: list[Way] = []

    if k in ("movie", "episode", "music"):
        order = ["vlc", "mpv"]
        last = settings["last_good"].get(k)
        if last in order:
            order.remove(last)
            order.insert(0, last)
        for tid in order:
            ways += _tool_ways(tid, lambda f, tid=tid: (
                _player_args(tid, item, settings, pr) + [str(target)], {}, None), progress)
        if system.default_is_browser(target):
            ways.append(Way("Default app (a web browser)", "default", available=False,
                            note="This PC would open it in a web browser, which cannot read it."))
        else:
            ways.append(Way("This PC's default app", "default"))

    elif k == "rom":
        sysm = item.system
        for found in tools.find_all("retroarch"):
            def build(found=found, sysm=sysm):
                ready = tools.localize(found, progress)
                core = None
                for c in (sysm.cores if sysm else ()):
                    core = tools.find_core(c, ready)
                    if core:
                        break
                if core is None:
                    names = ", ".join(sysm.cores) if sysm else "any"
                    raise OSError(f"No RetroArch core for {sysm.name if sysm else 'this game'} "
                                  f"(looked for: {names}).")
                return (ready.argv + ["-L", str(core), "--appendconfig", str(_retroarch_cfg(item)),
                                      str(target)], ready.env, None)
            ways.append(Way(found.label, "retroarch", build, found))
        if not ways:
            ways.append(Way("RetroArch (not found)", "retroarch", None, None, available=False,
                            note="RetroArch is not on this PC or the drive."))

    elif k in ("game_windows", "program") and target.suffix.lower() in (".exe", ".bat", ".cmd", ".lnk"):
        if paths.IS_WINDOWS:
            if target.suffix.lower() == ".lnk":
                ways.append(Way("Windows", "default"))
            else:
                ways.append(Way("Windows", "direct",
                                lambda: ([str(target)], {}, target.parent)))
        else:
            for tid in ("proton", "wine"):
                ways += [w for w in _tool_ways(tid, lambda f: (
                    [str(target)], _wine_env(), target.parent), progress)]

    elif k in ("game_linux", "program") and paths.IS_LINUX:
        ways += _linux_native_ways(target)

    elif k == "installer":
        ext = target.suffix.lower()
        if ext == ".msi" and paths.IS_WINDOWS:
            ways.append(Way("Windows Installer", "direct",
                            lambda: (["msiexec", "/i", str(target)], {}, target.parent)))
        elif ext == ".deb" and paths.IS_LINUX and shutil.which("pkexec"):
            ways.append(Way("Install with apt (asks for your password)", "pkexec",
                            lambda: (["pkexec", "apt-get", "install", "-y", str(target)], {}, None)))
        else:
            ways.append(Way("This PC's default app", "default"))

    elif k == "archive":
        ways.append(Way("This PC's default app", "default"))

    else:
        ways.append(Way("This PC's default app", "default"))

    # A remembered choice for this exact item goes first.
    chosen = settings.recall(item.key).get("way")
    if chosen:
        ways.sort(key=lambda w: 0 if w.label == chosen else 1)
    return ways


def _linux_native_ways(target: Path) -> list[Way]:
    ways: list[Way] = []
    low = target.name.lower()
    executable = os.access(target, os.X_OK)
    if low.endswith(".sh"):
        ways.append(Way("bash", "bash", lambda: (["bash", str(target)], {}, target.parent)))
        return ways
    if low.endswith(".appimage"):
        def localized():
            f = tools.Found(tools.Tool("app", target.stem, ""), "drive", [], target,
                            carried=True, needs_localize=True)
            ready = tools.localize(f)
            return ready.argv, {}, target.parent
        if executable:
            ways.append(Way("Run directly", "direct", lambda: ([str(target)], {}, target.parent)))
        ways.append(Way("Copy to this PC and run", "localize", localized))
        return ways
    if executable:
        ways.append(Way("Run directly", "direct", lambda: ([str(target)], {}, target.parent)))
    loader = next((p for p in ("/lib64/ld-linux-x86-64.so.2", "/lib/ld-linux-x86-64.so.2")
                   if os.path.exists(p)), None)
    if loader:
        # Runs a program that the drive cannot mark executable, without copying it.
        ways.append(Way("Run through the system loader", "loader",
                        lambda: ([loader, str(target)], {}, target.parent)))
    return ways


# --- trying them ------------------------------------------------------------------

def try_ways(item: Item, ways: list[Way], progress: Callable[[str], None] | None = None) -> Outcome:
    out = Outcome(ok=False)
    for way in ways:
        if not way.available:
            out.attempts.append(Attempt(way.label, False, way.note))
            continue
        if progress:
            progress(f"Opening {item.title} with {way.label}…")
        try:
            if way.tool_id == "default":
                proc = system.open_with_default(item.target)
                if proc is None:
                    out.ok, out.used = True, way.label
                    out.attempts.append(Attempt(way.label, True))
                    return out
                argv_desc = "xdg-open"
            else:
                argv, env, cwd = way.build()  # type: ignore[misc]
                full_env = {**os.environ, **env}
                if "PATH" in env:
                    full_env["PATH"] = env["PATH"]
                proc = subprocess.Popen(argv, cwd=str(cwd) if cwd else None, env=full_env,
                                        start_new_session=True, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
                argv_desc = Path(argv[0]).name
        except OSError as e:
            out.attempts.append(Attempt(way.label, False, str(e)))
            out.failed_tool = way.tool_id
            continue
        code = _wait_briefly(proc)
        if code is None or code == 0:
            out.ok, out.used = True, way.label
            out.attempts.append(Attempt(way.label, True))
            _drain_later(proc)
            return out
        err = ""
        try:
            err = (proc.stderr.read() or b"").decode(errors="replace").strip() if proc.stderr else ""
        except (OSError, ValueError):
            pass
        tail = " ".join(err.splitlines()[-3:])[:300]
        out.attempts.append(Attempt(way.label, False,
                                    f"{argv_desc} stopped with code {code}" + (f": {tail}" if tail else "")))
        out.failed_tool = way.tool_id
    return out


def _wait_briefly(proc: subprocess.Popen) -> int | None:
    end = time.monotonic() + FAIL_WINDOW
    while time.monotonic() < end:
        code = proc.poll()
        if code is not None:
            return code
        time.sleep(0.1)
    return None


def _drain_later(proc: subprocess.Popen) -> None:
    """Keep reading a running program's error output so it never blocks on a full pipe."""
    import threading

    def drain():
        try:
            if proc.stderr:
                for _ in proc.stderr:
                    pass
        except (OSError, ValueError):
            pass
    threading.Thread(target=drain, daemon=True).start()
