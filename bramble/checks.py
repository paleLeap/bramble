"""Problems Bramble can see before (or after) opening something, each with fixes.

A fix is either an action Bramble can do right now (`run`, returns ok, message)
or a Troubleshooting Guide topic to open (`guide`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import kinds, paths, probe, system, tools
from .library import Item


@dataclass
class Fix:
    label: str
    run: Callable[[], tuple[bool, str]] | None = None
    guide: str = ""               # guide topic id
    download: str = ""            # tool id to look up a newer/missing copy of
    install: str = ""             # tool id to install on this PC
    asks_password: bool = False


@dataclass
class Issue:
    level: str                    # "info", "warn", "bad"
    title: str
    detail: str
    fixes: list[Fix] = field(default_factory=list)


def _tool_missing(tool_id: str) -> bool:
    return not tools.find_all(tool_id)


def _get_tool_fixes(tool_id: str) -> list[Fix]:
    t = tools.TOOLS[tool_id]
    fixes = []
    if system.install_command(t.install_hint_linux, t.install_hint_windows):
        fixes.append(Fix(f"Install {t.name} on this PC", install=tool_id,
                         asks_password=paths.IS_LINUX))
    if t.carried_linux if paths.IS_LINUX else t.carried_windows:
        fixes.append(Fix(f"Download {t.name} for Bramble", download=tool_id))
    return fixes


def before_open(item: Item, pr: probe.Probe | None) -> list[Issue]:
    issues: list[Issue] = []
    k = item.kind

    if item.busy:
        issues.append(Issue("warn", "Still downloading",
                            "This file changed in the last minute and a half, so it is probably "
                            "still downloading or copying. It may stop or skip partway through.",
                            [Fix("About unfinished downloads", guide="still-downloading")]))

    if k in ("movie", "episode", "music"):
        if _tool_missing("vlc") and _tool_missing("mpv"):
            issues.append(Issue("bad", "No video player",
                                "Neither VLC nor mpv is on this PC or the drive. The PC's own "
                                "default app will be tried, which may not handle this file.",
                                _get_tool_fixes("vlc") + [Fix("Why this matters", guide="no-player")]))
        if pr and pr.ok and k != "music":
            if pr.first_audio in probe.PASSTHROUGH_AUDIO and system.passthrough_risk():
                issues.append(Issue("warn", "Sound may be silent on the TV",
                                    f"This film's sound is {pr.first_audio.upper()} (Dolby/DTS) and the "
                                    "HDMI output claims it can take that undecoded. Many TVs then play "
                                    "nothing.",
                                    [Fix("Send plain sound to the TV", run=system.fix_passthrough),
                                     Fix("About silent TVs", guide="no-sound-tv")]))
            want = probe.pick_subtitle(pr, "full")
            if not want and not item.sidecar_subs:
                issues.append(Issue("info", "No English subtitles in this file",
                                    "There is no English subtitle track inside the file and no "
                                    ".srt beside it.",
                                    [Fix("How to get subtitles", guide="subtitles")]))
            elif want and want.image_based:
                issues.append(Issue("info", "Subtitles are pictures",
                                    "The English subtitles are image-based (Blu-ray style). VLC shows "
                                    "them; some players cannot.", []))
        elif pr and not pr.ok and k != "music" and probe.ffprobe_cmd():
            issues.append(Issue("bad", "The file could not be read",
                                f"ffprobe could not read it ({pr.error}). It may be incomplete or "
                                "damaged.", [Fix("Damaged or incomplete files", guide="damaged-file")]))
        ext = system.idle_external_display()
        if ext:
            issues.append(Issue("info", "A TV or monitor is plugged in but dark",
                                f"{ext['name']} is connected and switched off on the computer's side.",
                                [Fix("Show the picture on it too", run=lambda e=ext: system.show_on_external(e)),
                                 Fix("About TVs and HDMI", guide="tv-blank")]))

    elif k == "rom":
        if item.system is None:
            issues.append(Issue("bad", "Unknown console",
                                "Bramble cannot tell which console this game is for. Put it in a "
                                "folder named after the console, for example Video Games/SNES.",
                                [Fix("Which folder names work", guide="rom-folders")]))
        if _tool_missing("retroarch"):
            issues.append(Issue("bad", "RetroArch is missing",
                                "Retro games are played through RetroArch, which is not on this PC "
                                "or the drive.", _get_tool_fixes("retroarch")))
        if item.system and item.system.bios:
            bios_dir = item.root / "Video Games" / "BIOS"
            have = {p.name.lower() for p in bios_dir.glob("*")} if bios_dir.is_dir() else set()
            for group in item.system.bios:
                if not have.intersection(g.lower() for g in group):
                    issues.append(Issue("bad", f"{item.system.name} needs a BIOS file",
                                        f"Put one of these in {bios_dir}: {', '.join(group[:3])}. "
                                        "Bramble cannot supply it; it comes from a console you own.",
                                        [Fix("About BIOS files", guide="bios")]))

    elif k in ("game_windows",) or (k == "program" and item.target.suffix.lower() == ".exe"):
        if paths.IS_LINUX and _tool_missing("proton") and _tool_missing("wine"):
            issues.append(Issue("bad", "Windows games need Proton or Wine on Linux",
                                "Neither GE-Proton nor Wine is on this PC or the drive.",
                                _get_tool_fixes("wine") + [Fix("Download GE-Proton for Bramble",
                                                               download="proton"),
                                                           Fix("About Windows games on Linux",
                                                               guide="windows-games-linux")]))
        if paths.IS_LINUX and k == "game_windows":
            issues.append(Issue("info", "Runs through Proton",
                                "Windows games run on Linux through Proton. Most work; anti-cheat "
                                "online games usually do not.",
                                [Fix("About Windows games on Linux", guide="windows-games-linux")]))

    elif k == "game_linux" and paths.IS_WINDOWS:
        issues.append(Issue("bad", "This is a Linux game",
                            "It cannot run on Windows.", [Fix("Why", guide="wrong-os")]))

    elif k == "installer" and paths.IS_WINDOWS and item.path.suffix.lower() == ".deb":
        issues.append(Issue("bad", "This is a Linux installer", "It cannot run on Windows.",
                            [Fix("Why", guide="wrong-os")]))

    return issues


def after_failure(item: Item, outcome) -> list[Issue]:
    """What to offer when nothing opened it."""
    issues: list[Issue] = []
    lines = "\n".join(f"• {a.way}: {a.detail or 'did not start'}" for a in outcome.attempts)
    fixes: list[Fix] = []
    if outcome.failed_tool in tools.TOOLS:
        t = tools.TOOLS[outcome.failed_tool]
        fixes.append(Fix(f"Look for a newer {t.name}", download=t.id))
    fixes.append(Fix("Troubleshooting Guide", guide="nothing-opens"))
    issues.append(Issue("bad", f"{item.title} did not open", lines or "Nothing could open it.", fixes))
    return issues
