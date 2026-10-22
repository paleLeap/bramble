"""Looking inside video and audio files with ffprobe, cached per file."""
from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, tools

_cache_lock = threading.Lock()
_CACHE_FILE = paths.cache_dir() / "probe.json"
_cache: dict | None = None

# Sound formats a TV may be sent undecoded ("passthrough") and then stay silent.
PASSTHROUGH_AUDIO = {"ac3", "eac3", "truehd", "dts", "mlp"}


@dataclass
class SubTrack:
    index: int          # position among the file's subtitle tracks (VLC --sub-track)
    language: str
    title: str
    codec: str

    @property
    def forced(self) -> bool:
        return "forced" in self.title.lower()

    @property
    def sdh(self) -> bool:
        return "sdh" in self.title.lower() or "hearing" in self.title.lower()

    @property
    def image_based(self) -> bool:
        return self.codec in ("hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle")


@dataclass
class Probe:
    ok: bool
    error: str = ""
    duration: float = 0.0
    video_codec: str = ""
    width: int = 0
    height: int = 0
    bit_depth: int = 8
    hdr: bool = False
    audio: list[dict] = field(default_factory=list)      # {codec, channels, language, title}
    subs: list[SubTrack] = field(default_factory=list)

    @property
    def resolution(self) -> str:
        # By width: wide films are cropped top and bottom (1920x800 is still 1080p).
        w = self.width
        if not w:
            return ""
        return "4K" if w >= 3200 else "1080p" if w >= 1700 else "720p" if w >= 1200 else \
            "480p" if w >= 640 else f"{self.height}p"

    @property
    def first_audio(self) -> str:
        return self.audio[0]["codec"] if self.audio else ""


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(_cache), encoding="utf-8")
    except OSError:
        pass


_ffprobe_cmd: list[str] | None = None


def ffprobe_cmd() -> list[str] | None:
    global _ffprobe_cmd
    if _ffprobe_cmd is None:
        for found in tools.find_all("ffprobe"):
            try:
                _ffprobe_cmd = tools.localize(found).argv
                break
            except OSError:
                continue
        else:
            _ffprobe_cmd = []
    return _ffprobe_cmd or None


def _parse(data: dict) -> Probe:
    pr = Probe(ok=True)
    try:
        pr.duration = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        pass
    sub_i = 0
    for s in data.get("streams", []):
        tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
        t = s.get("codec_type")
        if t == "video" and not pr.video_codec and s.get("disposition", {}).get("attached_pic") != 1:
            pr.video_codec = s.get("codec_name", "")
            pr.width, pr.height = s.get("width", 0) or 0, s.get("height", 0) or 0
            pix = s.get("pix_fmt", "")
            pr.bit_depth = 10 if "10" in pix else 12 if "12" in pix else 8
            pr.hdr = s.get("color_transfer") in ("smpte2084", "arib-std-b67")
        elif t == "audio":
            pr.audio.append({"codec": s.get("codec_name", ""), "channels": s.get("channels", 0),
                             "language": tags.get("language", ""), "title": tags.get("title", "")})
        elif t == "subtitle":
            pr.subs.append(SubTrack(sub_i, tags.get("language", ""), tags.get("title", ""),
                                    s.get("codec_name", "")))
            sub_i += 1
    return pr


def probe(path: Path, timeout: float = 15) -> Probe:
    try:
        st = path.stat()
    except OSError as e:
        return Probe(ok=False, error=str(e))
    key = f"{path}|{st.st_size}|{int(st.st_mtime)}"
    with _cache_lock:
        cached = _load_cache().get(key)
    if cached is not None:
        return _parse(cached)
    cmd = ffprobe_cmd()
    if not cmd:
        return Probe(ok=False, error="ffprobe is not available")
    try:
        r = subprocess.run(cmd + ["-v", "error", "-print_format", "json", "-show_format",
                                  "-show_streams", str(path)],
                           capture_output=True, text=True, timeout=timeout)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return Probe(ok=False, error=str(e))
    if not data.get("streams"):
        return Probe(ok=False, error=(r.stderr or "no streams found").strip()[:300])
    with _cache_lock:
        _load_cache()[key] = data
        _save_cache()
    return _parse(data)


def pick_subtitle(pr: Probe, mode: str, language: str = "eng") -> SubTrack | None:
    """The subtitle track to start with. mode: full | forced | off."""
    if mode == "off" or not pr.subs:
        return None
    lang = [s for s in pr.subs if s.language.lower().startswith(language[:2])]
    if mode == "forced":
        return next((s for s in lang if s.forced), None)
    plain = [s for s in lang if not s.forced and not s.sdh]
    sdh = [s for s in lang if s.sdh and not s.forced]
    return (plain or sdh or [None])[0]
