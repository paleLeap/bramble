"""Bramble's settings, kept per PC as JSON in the config folder."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import paths

DEFAULTS = {
    # Extra library roots besides the drive's MARROW and ~/MARROW.
    "library_roots": [],
    # Folders whose new media is offered for filing on the INBOX page.
    "inbox_folders": [],          # empty = the Downloads folder
    # Subtitles when a film opens: "full" (complete English), "forced" (only
    # foreign-language lines), "off".
    "subtitles": "full",
    "subtitle_language": "eng",
    "fullscreen_video": True,
    # Per-file memory: {path: {"runner": id, "exe": path}}.
    "remembered": {},
    # Which program last worked for each kind, so it is tried first next time.
    "last_good": {},
    # Default destination per category when filing (category -> folder).
    "file_to": {},
    # Unfinished downloads, resumed when Bramble opens: [{link, folder}].
    "downloads": [],
    # Where the search box looks: module names in bramble/sources (the owner's choice).
    "sources": [],
    # Plugins switched off with the leaf beside the search box (by file name).
    "sources_off": [],
    # Categories in the order the person made them (folder names, any case).
    "category_order": [],
    # Sites whose own search page Bramble opens in the browser: [{name, url}], where the
    # word "bramble" in url stands for what is searched (the person searched it there).
    "sites": [],
    # The torrent program tried first: "qbittorrent" or "aria2" (the other is the fallback).
    "torrent_program": "qbittorrent",
}


class Settings:
    def __init__(self) -> None:
        self.path = paths.config_dir() / "settings.json"
        self.data = dict(DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value) -> None:
        self.data[key] = value
        self.save()

    def remember(self, item_path: str, **values) -> None:
        mem = dict(self.data.get("remembered", {}))
        mem[item_path] = {**mem.get(item_path, {}), **values}
        self["remembered"] = mem

    def recall(self, item_path: str) -> dict:
        return self.data.get("remembered", {}).get(item_path, {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def inbox_folders(self) -> list[Path]:
        chosen = [Path(p) for p in self["inbox_folders"]]
        return chosen or [paths.downloads_dir()]
