"""Downloading what someone pastes: torrent files, magnet links, direct links.

Bramble does it itself with aria2 (carried on the drive, or on the PC), straight
into the category's folder. Unfinished downloads are remembered and resumed the
next time Bramble opens (aria2 --continue picks up where it stopped).
"""
from __future__ import annotations

import re
import subprocess
import threading
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

    @property
    def state_text(self) -> str:
        if self.failed:
            return "failed"
        if self.finished:
            return "done"
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
                self.start(d["link"], folder, remember=False)

    def _remember(self) -> None:
        self.settings["downloads"] = [{"link": j.link, "folder": str(j.folder)}
                                      for j in self.jobs if not j.finished]

    def start(self, link: str, folder: Path, remember: bool = True) -> Job:
        job = Job(link.strip(), folder, title_of(link))
        self.jobs.append(job)
        if remember:
            self._remember()
        cmd = self.aria2()
        if not cmd:
            job.failed, job.finished = True, True
            job.error = "aria2, the downloader Bramble uses, is not on this PC or the drive."
            job.needs = "aria2"
            self._remember()
            return job
        folder.mkdir(parents=True, exist_ok=True)
        args = cmd + [f"--dir={folder}", "--continue=true", "--seed-time=0",
                      "--summary-interval=1", "--console-log-level=error",
                      "--file-allocation=none", "--enable-color=false",
                      "--bt-save-metadata=false", "--auto-file-renaming=false",
                      "--allow-overwrite=false", job.link]
        try:
            job.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, errors="replace", bufsize=1,
                                        **({"creationflags": 0x08000000} if paths.IS_WINDOWS else {}))
        except OSError as e:
            job.failed, job.finished, job.error = True, True, str(e)
            self._remember()
            return job
        threading.Thread(target=self._watch, args=(job,), daemon=True).start()
        return job

    def _watch(self, job: Job) -> None:
        tail: list[str] = []
        assert job.proc and job.proc.stdout
        for line in job.proc.stdout:
            m = re.search(r"\((\d{1,3})%\)", line)
            if m and "B/0B" not in line:
                job.percent = int(m.group(1))
            if line.strip():
                tail = (tail + [line.strip()])[-6:]
        code = job.proc.wait()
        job.finished = True
        if code == 0:
            job.percent = 100
        else:
            job.failed = True
            job.error = REASONS.get(code, f"aria2 stopped (code {code}).")
            detail = next((t for t in reversed(tail) if "error" in t.lower() or "exception" in t.lower()), "")
            if detail:
                job.error += " " + detail[:200]
        self._remember()
        self.on_change(job)

    def retry_failed(self) -> None:
        """Start every failed download again (after its problem was fixed)."""
        failed = [j for j in self.jobs if j.failed]
        self.jobs = [j for j in self.jobs if not j.failed]
        for j in failed:
            self.start(j.link, j.folder)

    def stop_all(self) -> None:
        for j in self.jobs:
            if j.proc and j.proc.poll() is None:
                j.proc.terminate()

    def for_folder(self, folders: list[Path]) -> list[Job]:
        keys = {str(f) for f in folders}
        return [j for j in self.jobs if str(j.folder) in keys and not (j.finished and not j.failed)]
