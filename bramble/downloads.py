"""Downloading what someone pastes: torrent files, magnet links, direct links.

Bramble runs the torrent programs itself: its own qBittorrent first (in the
background, see qbit.py), aria2 when qBittorrent cannot start or fails. Unfinished
downloads are remembered and resumed the next time Bramble opens.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import paths, tools

LINK = re.compile(r"(?i)^(magnet:\?|https?://|ftp://)")

# aria2's own error codes, said plainly (https://aria2.github.io/manual/en/html/aria2c.html#exit-status)
REASONS = {
    1: "Something went wrong while downloading.",
    2: "The download timed out.",
    3: "The link points to nothing.",
    6: "Could not reach the internet or the server.",
    7: "Stopped before it finished.",
    9: "Not enough space on the disk.",
    13: "A file with that name is already there.",
    19: "The address could not be found. Check the internet connection.",
    22: "The server refused the request.",
    24: "The link needs a login.",
}


def looks_like_link(text: str) -> bool:
    t = text.strip()
    return bool(LINK.match(t)) or (t.lower().endswith(".torrent") and Path(t).exists())


def title_of(link: str) -> str:
    link = link.strip()
    if link.lower().startswith("magnet:"):
        dn = parse_qs(urlparse(link).query).get("dn")
        if dn:
            return unquote(dn[0])
        return "magnet link"
    if link.lower().endswith(".torrent") and Path(link).exists():
        return Path(link).stem
    name = unquote(Path(urlparse(link).path).name)
    return name or urlparse(link).netloc


@dataclass
class Job:
    link: str
    folder: Path
    title: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    percent: int = -1
    finished: bool = False
    failed: bool = False
    error: str = ""
    needs: str = ""                  # a tool id whose absence caused the failure
    proc: subprocess.Popen | None = None
    marrow: Path | None = None       # held downloads: the library they are filed into
    stage: str = ""                  # "checking", "ready", "held" once the download is done
    reasons: list = field(default_factory=list)   # why a held one was held
    landed: Path | None = None       # where a ready one went
    kind: str = ""
    speed: str = ""                  # "3.2MiB" a second, from aria2's readout
    eta: str = ""                    # "6m12s"
    into: Path | None = None         # file into this folder (a category's "+"), not by kind
    engine: str = ""                 # "qBittorrent" or "aria2"
    waiting: bool = False            # nobody is sharing it (yet)

    @property
    def state_text(self) -> str:
        if self.failed:
            return "failed"
        if self.stage:
            return self.stage
        if self.finished:
            return "done"
        if self.waiting:
            return "waiting for someone sharing it"
        return f"{self.percent}%" if self.percent >= 0 else "starting"


class Downloads:
    def __init__(self, settings, on_change):
        self.settings = settings
        self.on_change = on_change            # called from a worker thread when a job ends
        self.jobs: list[Job] = []

    def aria2(self) -> list[str] | None:
        for found in tools.find_all("aria2"):
            try:
                return tools.localize(found).argv
            except OSError:
                continue
        return None

    def resume_saved(self) -> None:
        for d in self.settings["downloads"]:
            folder = Path(d["folder"])
            if folder.is_dir():
                self.start(d["link"], folder, remember=False,
                           marrow=Path(d["marrow"]) if d.get("marrow") else None,
                           title=d.get("title", ""), into=Path(d["into"]) if d.get("into") else None)

    def _remember(self) -> None:
        self.settings["downloads"] = [
            {"link": j.link, "folder": str(j.folder), "title": j.title,
             **({"marrow": str(j.marrow)} if j.marrow else {}),
             **({"into": str(j.into)} if j.into else {})}
            for j in self.jobs if not j.finished]

    def start(self, link: str, folder: Path, remember: bool = True, marrow: Path | None = None,
              title: str = "", into: Path | None = None) -> Job:
        """Download into `folder`. With `marrow`, `folder` is a holding folder: when the
        download finishes it is checked (vet.py) and filed into that library (or `into`)."""
        job = Job(link.strip(), folder, title or title_of(link), marrow=marrow, into=into)
        self.jobs.append(job)
        if remember:
            self._remember()
        folder.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        """qBittorrent first; aria2 if it cannot start, will not take the link, or fails."""
        from . import qbit
        why = ""
        try:
            q = qbit.get()
            job.engine = "qBittorrent"
            if self._follow_qbit(job, q):
                return
            why = job.error
        except OSError as e:
            why = str(e)
        job.failed = job.finished = False
        job.error, job.percent, job.engine = "", -1, ""
        self._start_aria2(job, why)

    def _follow_qbit(self, job: Job, q) -> bool:
        """Add the torrent and watch it to the end. False if qBittorrent gave up on it."""
        import hashlib
        tag = "bramble-" + hashlib.sha1(job.link.encode()).hexdigest()[:12]
        if q.info(tag) is None:
            try:
                q.add(job.link, job.folder, tag)
            except OSError as e:
                job.error = str(e)
                return False
        seen_at = time.monotonic()
        stalled_since = None
        done_states = {"uploading", "stalledUP", "pausedUP", "stoppedUP", "queuedUP", "forcedUP"}
        while True:
            time.sleep(1)
            try:
                t = q.info(tag)
            except OSError:
                if not q.alive():
                    job.error = "qBittorrent stopped answering."
                    return False
                continue
            if t is None:
                if time.monotonic() - seen_at > 60:
                    job.error = "qBittorrent lost track of it."
                    return False
                continue
            seen_at = time.monotonic()
            state = t.get("state", "")
            job.percent = int(float(t.get("progress", 0)) * 100)
            rate = int(t.get("dlspeed", 0))
            job.speed = _human(rate) if rate else ""
            eta = int(t.get("eta", 8640000))
            job.eta = _span(eta) if 0 < eta < 8640000 else ""
            nobody = state in ("stalledDL", "metaDL") and int(t.get("num_seeds", 0)) == 0 and rate == 0
            stalled_since = (stalled_since or time.monotonic()) if nobody else None
            job.waiting = bool(stalled_since and time.monotonic() - stalled_since > 120)
            if state in ("error", "missingFiles"):
                job.error = "qBittorrent reported a problem with it."
                return False
            if float(t.get("progress", 0)) >= 1.0 or state in done_states:
                job.percent = 100
                q.remove(t["hash"], delete_files=False)       # stop sharing; keep the files
                self._finish(job, ok=True)
                return True

    def _finish(self, job: Job, ok: bool, code: int = 0, detail: str = "") -> None:
        if ok:
            job.percent = 100
            if job.marrow is not None:
                self._vet(job)
            job.finished = True
        else:
            job.finished = True
            job.failed = True
            job.error = REASONS.get(code, f"aria2 stopped (code {code}).") + (f" {detail}" if detail else "")
        self._remember()
        self.on_change(job)

    def _start_aria2(self, job: Job, why: str = "") -> None:
        folder = job.folder
        cmd = self.aria2()
        if not cmd:
            job.failed, job.finished = True, True
            job.error = ("Neither torrent program could run. " + (f"qBittorrent: {why} " if why else "")
                         + "aria2 is not on this PC or the drive.")
            job.needs = "aria2"
            self._remember()
            self.on_change(job)
            return
        args = cmd + [f"--dir={folder}", "--continue=true", "--seed-time=0",
                      "--summary-interval=1", "--console-log-level=error",
                      "--enable-color=false",   # (file-allocation=none/trunc stall web-seeded torrents)
                      "--bt-save-metadata=false", "--auto-file-renaming=false",
                      "--allow-overwrite=false", job.link]
        try:
            job.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, errors="replace", bufsize=1,
                                        **({"creationflags": 0x08000000} if paths.IS_WINDOWS else {}))
        except OSError as e:
            job.failed, job.finished, job.error = True, True, str(e)
            self._remember()
            self.on_change(job)
            return
        job.engine = "aria2"
        self._watch(job)

    def _watch(self, job: Job) -> None:
        tail: list[str] = []
        assert job.proc and job.proc.stdout
        for line in job.proc.stdout:
            m = re.search(r"\((\d{1,3})%\)", line)
            if m and "B/0B" not in line:
                job.percent = int(m.group(1))
                sp = re.search(r"DL:([\d.]+[KMG]?i?B)", line)
                et = re.search(r"ETA:(\w+)", line)
                job.speed = sp.group(1) if sp else ""
                job.eta = et.group(1) if et else ""
            if line.strip():
                tail = (tail + [line.strip()])[-6:]
        code = job.proc.wait()
        detail = next((t for t in reversed(tail) if "error" in t.lower() or "exception" in t.lower()), "")
        self._finish(job, ok=(code == 0), code=code, detail=detail[:200])

    def _vet(self, job: Job) -> None:
        """Check what arrived in the holding folder; file it, or hold it with reasons."""
        from . import vet
        job.stage = "checking"
        try:
            inside = [p for p in job.folder.iterdir() if not p.name.endswith(".aria2")]
            root = inside[0] if len(inside) == 1 else job.folder
            v = vet.check(root)
            job.kind = v.kind
            if v.ok:
                job.landed = _named(vet.file_into_library(root, v, job.marrow, into=job.into), job.title)
                job.stage = "ready"
                shutil.rmtree(job.folder, ignore_errors=True)   # what is left: site adverts
            else:
                job.stage = "held"
                job.reasons = v.reasons
        except Exception as e:
            job.stage = "held"
            job.reasons = [f"Could not check it: {e}"]

    def keep_anyway(self, job: Job) -> None:
        """The person looked at a held download and chose to keep it."""
        from . import vet
        inside = [p for p in job.folder.iterdir() if not p.name.endswith(".aria2")]
        root = inside[0] if len(inside) == 1 else job.folder
        v = vet.check(root)
        v.keep = v.keep or [p for p in root.rglob("*") if p.is_file()] if root.is_dir() else [root]
        job.landed = vet.file_into_library(root, v, job.marrow, into=job.into)
        job.stage, job.reasons = "ready", []
        shutil.rmtree(job.folder, ignore_errors=True)

    def throw_away(self, job: Job) -> None:
        """Delete a held download. Only ever inside Bramble's own holding folder."""
        if job.marrow is not None and ".holding" in job.folder.parts:
            shutil.rmtree(job.folder, ignore_errors=True)
        self.jobs = [j for j in self.jobs if j is not job]

    def retry_failed(self) -> None:
        """Start every failed download again (after its problem was fixed)."""
        failed = [j for j in self.jobs if j.failed]
        self.jobs = [j for j in self.jobs if not j.failed]
        for j in failed:
            self.start(j.link, j.folder, marrow=j.marrow, title=j.title, into=j.into)

    def stop_all(self) -> None:
        from . import qbit
        for j in self.jobs:
            if j.proc and j.proc.poll() is None:
                j.proc.terminate()
        qbit.shutdown()

    def for_folder(self, folders: list[Path]) -> list[Job]:
        keys = {str(f) for f in folders}
        return [j for j in self.jobs if str(j.folder) in keys and not (j.finished and not j.failed)]


def _named(path: Path, title: str) -> Path:
    """A single file from a search keeps the result's name, not the site's code name
    ("ava11109vnb1.mpeg" becomes "Duck and Cover.mpeg")."""
    if not path.is_file() or not title:
        return path
    clean = re.sub(r'[\\/:*?"<>|]+', " ", title).strip()
    target = path.with_name(clean + path.suffix)
    if target != path and not target.exists():
        path.rename(target)
        return target
    return path


def _human(rate: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if rate < 1024 or unit == "GB":
            return f"{rate:.0f}{unit}" if unit in ("B", "KB") else f"{rate:.1f}{unit}"
        rate /= 1024
    return ""


def _span(secs: int) -> str:
    h, rem = divmod(secs, 3600)
    m, s_ = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s_:02d}s" if m else f"{s_}s"
