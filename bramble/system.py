"""The PC around Bramble: screens, sound, default apps, installing things.

Every function here answers quickly and fails quietly (returns None/False) on a
PC where the tool it asks is missing, so the window never stalls on a check.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import paths


def _run(cmd: list[str], timeout: float = 4) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


# --- screens --------------------------------------------------------------------

def displays() -> list[dict]:
    """[{name, connected, active, internal, modes:[...]}] on Linux/X11."""
    if not paths.IS_LINUX or not shutil.which("xrandr") or not os.environ.get("DISPLAY"):
        return []
    r = _run(["xrandr", "--query"])
    if not r or r.returncode:
        return []
    out, cur = [], None
    for line in r.stdout.splitlines():
        m = re.match(r"^(\S+) (connected|disconnected)( primary)?\s*(\d+x\d+\+\d+\+\d+)?", line)
        if m:
            cur = {"name": m.group(1), "connected": m.group(2) == "connected",
                   "active": bool(m.group(4)), "internal": m.group(1).lower().startswith(("edp", "lvds", "dsi")),
                   "modes": []}
            out.append(cur)
        elif cur is not None and line.startswith("   "):
            mm = re.match(r"\s+(\d+x\d+)", line)
            if mm:
                cur["modes"].append(mm.group(1))
    return out


def idle_external_display() -> dict | None:
    """A TV or monitor that is plugged in but not showing anything."""
    for d in displays():
        if d["connected"] and not d["internal"] and not d["active"]:
            return d
    return None


def show_on_external(d: dict) -> tuple[bool, str]:
    """Mirror the main screen onto the plugged-in TV/monitor."""
    internal = next((x for x in displays() if x["internal"] and x["active"]), None)
    cmd = ["xrandr", "--output", d["name"], "--auto"]
    if internal:
        mode = internal["modes"][0] if internal["modes"] else None
        if mode and mode in d["modes"]:
            cmd = ["xrandr", "--output", d["name"], "--mode", mode]
        cmd += ["--same-as", internal["name"]]
    r = _run(cmd, timeout=10)
    if r and r.returncode == 0:
        return True, f"{d['name']} now shows the same picture as this screen."
    return False, (r.stderr.strip() if r else "xrandr did not answer")


# --- sound ----------------------------------------------------------------------

def _pw_dump() -> list[dict]:
    r = _run(["pw-dump"], timeout=5)
    if not r or r.returncode:
        return []
    try:
        return json.loads(r.stdout)
    except ValueError:
        return []


def default_sink() -> dict | None:
    """{id, name, description, hdmi, codecs} for the PipeWire default output."""
    if not paths.IS_LINUX or not shutil.which("pw-dump"):
        return None
    objs = _pw_dump()
    default_name = None
    for o in objs:
        if o.get("type", "").endswith("Metadata") and o.get("props", {}).get("metadata.name") == "default":
            for m in o.get("metadata", []):
                if m.get("key") == "default.audio.sink":
                    v = m.get("value")
                    default_name = v.get("name") if isinstance(v, dict) else None
    for o in objs:
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("media.class") != "Audio/Sink":
            continue
        if default_name and props.get("node.name") != default_name:
            continue
        codecs = []
        for p in (info.get("params") or {}).get("Props") or []:
            if "iec958Codecs" in p:
                codecs = p["iec958Codecs"]
        name = props.get("node.name", "")
        return {"id": o["id"], "name": name, "description": props.get("node.description", ""),
                "hdmi": "hdmi" in name.lower() or "hdmi" in props.get("node.description", "").lower(),
                "codecs": codecs}
    return None


def passthrough_risk() -> dict | None:
    """The default output is HDMI and claims to take undecoded Dolby/DTS. With
    VLC that means silence on many TVs (seen on this PC 2026-10-21)."""
    s = default_sink()
    if s and s["hdmi"] and any(c != "PCM" for c in s["codecs"]):
        return s
    return None


WIREPLUMBER_RULE = """# Written by Bramble: send plain decoded sound over HDMI. With AC3/EAC3/TrueHD
# advertised, players pass Dolby audio through undecoded and many TVs stay silent.
monitor.alsa.rules = [
  {
    matches = [ { node.name = "~alsa_output.*hdmi.*" } ]
    actions = { update-props = { iec958.codecs = [ "PCM" ] } }
  }
]
"""


def fix_passthrough() -> tuple[bool, str]:
    s = default_sink()
    if not s:
        return False, "No sound output found."
    r = _run(["pw-cli", "set-param", str(s["id"]), "Props", '{ iec958Codecs: [ "PCM" ] }'])
    conf = Path.home() / ".config/wireplumber/wireplumber.conf.d/51-hdmi-pcm-only.conf"
    try:
        if not conf.exists():
            conf.parent.mkdir(parents=True, exist_ok=True)
            conf.write_text(WIREPLUMBER_RULE)
    except OSError:
        pass
    if r and r.returncode == 0:
        return True, ("The TV now gets plain sound. Restart the film if it is already "
                      "playing silently.")
    return False, (r.stderr.strip() if r else "pw-cli is not available")


def hdmi_sinks() -> list[dict]:
    out = []
    for o in _pw_dump():
        props = (o.get("info") or {}).get("props") or {}
        if props.get("media.class") == "Audio/Sink" and "hdmi" in props.get("node.name", "").lower():
            out.append({"id": o["id"], "name": props.get("node.name"),
                        "description": props.get("node.description", "")})
    return out


def send_sound_to(sink_id: int) -> bool:
    r = _run(["wpctl", "set-default", str(sink_id)])
    return bool(r and r.returncode == 0)


# --- default apps ----------------------------------------------------------------

BROWSERS = re.compile(r"(?i)firefox|chrom|brave|opera|vivaldi|edge|epiphany|falkon|librewolf|zen")


def default_app_for(path: Path) -> str | None:
    """The .desktop file Linux would open this with."""
    if not paths.IS_LINUX or not shutil.which("xdg-mime"):
        return None
    r = _run(["xdg-mime", "query", "filetype", str(path)])
    if not r or not r.stdout.strip():
        return None
    r2 = _run(["xdg-mime", "query", "default", r.stdout.strip()])
    return r2.stdout.strip() if r2 else None


def default_is_browser(path: Path) -> bool:
    app = default_app_for(path)
    return bool(app and BROWSERS.search(app))


def open_with_default(path: Path) -> subprocess.Popen | None:
    if paths.IS_WINDOWS:
        os.startfile(str(path))          # type: ignore[attr-defined]
        return None
    return subprocess.Popen(["xdg-open", str(path)], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def show_in_folder(path: Path) -> None:
    if paths.IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        target = path if path.is_dir() else path.parent
        subprocess.Popen(["xdg-open", str(target)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- installing ---------------------------------------------------------------------

def install_command(package_linux: str = "", winget_id: str = "") -> list[str] | None:
    """The command that installs a program on this PC (asks for a password or UAC itself)."""
    if paths.IS_WINDOWS:
        if winget_id and shutil.which("winget"):
            return ["winget", "install", "-e", "--id", winget_id,
                    "--accept-package-agreements", "--accept-source-agreements"]
        return None
    if not package_linux:
        return None
    if shutil.which("apt-get") and shutil.which("pkexec"):
        return ["pkexec", "apt-get", "install", "-y", package_linux]
    if shutil.which("dnf") and shutil.which("pkexec"):
        return ["pkexec", "dnf", "install", "-y", package_linux]
    if shutil.which("pacman") and shutil.which("pkexec"):
        return ["pkexec", "pacman", "-S", "--noconfirm", package_linux]
    return None


def os_label() -> str:
    if paths.IS_WINDOWS:
        return "Windows"
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return "Linux"
