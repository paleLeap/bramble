"""Bramble's own qBittorrent, run in the background and driven through its Web API.

It has its own profile folder (never the person's own qBittorrent settings or
torrents), listens only on this PC, and is shut down when Bramble closes. On
Linux it is qbittorrent-nox (no window); on Windows qbittorrent.exe started
minimised.
"""
from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import paths, tools

_lock = threading.Lock()
_instance: "Qbit | None" = None


class QbitError(OSError):
    pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# DHT's first contacts. qBittorrent's own copy looks names up with its built-in resolver,
# which on some PCs fails for minutes (seen 2026-10-23: no DHT nodes for three minutes);
# Bramble looks them up with the PC's resolver and hands over the addresses as well.
BOOTSTRAP = ("dht.libtorrent.org:25401", "dht.transmissionbt.com:6881", "router.bittorrent.com:6881",
             "router.utorrent.com:6881", "dht.aelitis.com:6881")


def _bootstrap_nodes(wait: float = 2.0) -> str:
    """The bootstrap list with each name's IPv4 addresses ahead of it (names kept as a fallback)."""
    from concurrent.futures import ThreadPoolExecutor, wait as wait_all

    def look(entry):
        host, port = entry.rsplit(":", 1)
        try:
            infos = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_DGRAM)
        except OSError:
            return []
        return sorted({f"{i[4][0]}:{port}" for i in infos})

    pool = ThreadPoolExecutor(len(BOOTSTRAP))
    futures = [pool.submit(look, e) for e in BOOTSTRAP]
    wait_all(futures, timeout=wait)
    pool.shutdown(wait=False)
    found = [a for f in futures if f.done() for a in f.result()]
    return ", ".join(dict.fromkeys(found + list(BOOTSTRAP)))


def _own_settings(save: str, port: int) -> dict[tuple[str, str], str]:
    """The settings Bramble needs. Everything else in the file is qBittorrent's own and stays
    (its listening port among them, so peers and the router know it from one run to the next)."""
    return {
        ("LegalNotice", "Accepted"): "true",
        ("BitTorrent", "Session\\DefaultSavePath"): save,
        ("BitTorrent", "Session\\GlobalMaxSeedingMinutes"): "0",
        # no sharing once it is down, and no opening of ports on the router (the owner's
        # choice, 2026-10-23, first set by Warden in this file)
        ("BitTorrent", "Session\\GlobalMaxRatio"): "0",
        ("BitTorrent", "Session\\ShareLimitAction"): "Stop",
        ("Network", "PortForwardingEnabled"): "false",
        ("BitTorrent", "Session\\AddTorrentStopped"): "false",
        ("BitTorrent", "Session\\QueueingSystemEnabled"): "false",   # start at once, never "queued"
        # quoted: unquoted commas would make it a list, which qBittorrent ignores
        ("BitTorrent", "Session\\DHTBootstrapNodes"): f'"{_bootstrap_nodes()}"',
        ("Preferences", "General\\Locale"): "en",
        ("Preferences", "General\\StartMinimized"): "true",
        ("Preferences", "General\\NoSplashScreen"): "true",
        ("Preferences", "General\\ExitConfirm"): "false",
        ("WebUI", "Enabled"): "true",
        ("WebUI", "Address"): "127.0.0.1",
        ("WebUI", "Port"): str(port),
        ("WebUI", "LocalHostAuth"): "false",
        ("WebUI", "CSRFProtection"): "false",
        ("WebUI", "HostHeaderValidation"): "false",
    }


def _write_config(conf: Path, own: dict[tuple[str, str], str]) -> None:
    """Set Bramble's keys in qBittorrent's ini, leaving every other line as qBittorrent wrote it."""
    sections: dict[str, list[str]] = {}
    current = None
    try:
        lines = conf.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if line.startswith("[") and line.rstrip().endswith("]"):
            current = line.strip()[1:-1]
            sections.setdefault(current, [])
        elif current is not None and line.strip():
            sections[current].append(line)
    for (section, key), value in own.items():
        rows = sections.setdefault(section, [])
        rows[:] = [r for r in rows if r.split("=", 1)[0] != key] + [f"{key}={value}"]
    # the old place for the web settings, from Bramble's first versions: qBittorrent moved them
    sections["Preferences"] = [r for r in sections.get("Preferences", []) if not r.startswith("WebUI\\")]
    conf.write_text("".join(f"[{name}]\n" + "".join(r + "\n" for r in rows) + "\n"
                            for name, rows in sections.items()), encoding="utf-8")


class Qbit:
    def __init__(self, argv: list[str]):
        self.port = _free_port()
        self.profile = paths.data_dir() / "qbittorrent"
        conf = self.profile / "qBittorrent" / "config" / "qBittorrent.conf"
        conf.parent.mkdir(parents=True, exist_ok=True)
        _clear_leftover(self.profile)          # before touching its file: a leftover copy rewrites it
        _write_config(conf, _own_settings(str(paths.data_dir() / "qbt-downloads").replace("\\", "/"),
                                          self.port))
        args = argv + [f"--profile={self.profile}", f"--webui-port={self.port}", "--confirm-legal-notice"]
        flags = {"creationflags": 0x08000000} if paths.IS_WINDOWS else {"start_new_session": True}
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        (self.profile / "bramble.pid").write_text(str(self.proc.pid))
        self.base = f"http://127.0.0.1:{self.port}/api/v2"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise QbitError(f"qBittorrent stopped as it started (code {self.proc.returncode}).")
            try:
                self.call("app/version")
                return
            except OSError:
                time.sleep(0.4)
        self.stop()
        raise QbitError("qBittorrent did not answer after 20 seconds.")

    def call(self, path: str, data: dict | None = None, files: dict | None = None, timeout: float = 10):
        url = f"{self.base}/{path}"
        if files:
            boundary = uuid.uuid4().hex
            body = b""
            for k, v in (data or {}).items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                         f"{v}\r\n").encode()
            for k, (name, blob) in files.items():
                body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                         f"filename=\"{name}\"\r\nContent-Type: application/x-bittorrent\r\n\r\n").encode()
                body += blob + b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            req = urllib.request.Request(url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        elif data is not None:
            req = urllib.request.Request(url, urllib.parse.urlencode(data).encode())
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
        try:
            return json.loads(text)
        except ValueError:
            return text

    def alive(self) -> bool:
        if self.proc.poll() is not None:
            return False
        try:
            self.call("app/version", timeout=3)
            return True
        except OSError:
            return False

    def add(self, link: str, save: Path, tag: str) -> None:
        fields = {"savepath": str(save), "tags": tag, "stopped": "false", "paused": "false",
                  "root_folder": "true"}
        p = Path(link)
        if not link.startswith(("magnet:", "http://", "https://")) and p.is_file():
            res = self.call("torrents/add", fields, files={"torrents": (p.name, p.read_bytes())})
        else:
            res = self.call("torrents/add", {**fields, "urls": link})
        if isinstance(res, str) and "fail" in res.lower():
            raise QbitError("qBittorrent would not take that link.")

    def info(self, tag: str) -> dict | None:
        rows = self.call("torrents/info?" + urllib.parse.urlencode({"tag": tag}))
        return rows[0] if rows else None

    def remove(self, torrent_hash: str, delete_files: bool = False) -> None:
        self.call("torrents/delete", {"hashes": torrent_hash, "deleteFiles": str(delete_files).lower()})

    def stop(self) -> None:
        try:
            self.call("app/shutdown", {}, timeout=3)
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _clear_leftover(profile: Path) -> None:
    """A copy left running by a Bramble that did not close properly holds the profile;
    stop it before starting a fresh one (only ever our own, by its recorded number)."""
    pidf = profile / "bramble.pid"
    try:
        pid = int(pidf.read_text().strip())
    except (OSError, ValueError):
        return
    try:
        if paths.IS_WINDOWS:
            # Windows reuses process numbers: only stop it if it really is qBittorrent
            seen = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                  capture_output=True, text=True, creationflags=0x08000000).stdout
            if "qbittorrent" in seen.lower():
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               creationflags=0x08000000)
        else:
            import os
            import signal
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
            if "qbittorrent" in cmd and str(profile) in cmd:
                os.kill(pid, signal.SIGTERM)
                time.sleep(1.5)
    except (OSError, ProcessLookupError):
        pass
    pidf.unlink(missing_ok=True)


def get() -> Qbit:
    """The running instance, started on first use. Raises QbitError when none can run."""
    global _instance
    with _lock:
        if _instance is not None and _instance.alive():
            return _instance
        last = "qBittorrent is not on this PC or the drive."
        for found in tools.find_all("qbittorrent"):
            try:
                ready = tools.localize(found)
                _instance = Qbit(ready.argv)
                return _instance
            except OSError as e:
                last = str(e)
        _instance = None
        raise QbitError(last)


def shutdown() -> None:
    global _instance
    with _lock:
        if _instance is not None:
            _instance.stop()
            _instance = None
