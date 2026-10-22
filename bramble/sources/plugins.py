"""qBittorrent search plugins: the same one-file-per-site plugins qBittorrent's own
search uses. Any plugin dropped into a plugins folder becomes a search source:

    <settings folder>/plugins/*.py           (this PC)
    <drive>/INNARDS/bramble/plugins/*.py      (the Hawthorn drive)

Bramble provides the `helpers` and `novaprinter` modules they import. Which
sites are searched is entirely up to whoever puts the plugins there.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import urllib.parse
from pathlib import Path

from .. import paths
from . import Result, parse_size, quality_of

_NOVA = Path(__file__).resolve().parent / "_nova"


def folders() -> list[Path]:
    out = [paths.config_dir() / "plugins"]
    out += [d / "INNARDS" / "bramble" / "plugins" for d in paths.find_drives()]
    return [f for f in out if f.is_dir()]


def found() -> list[Path]:
    seen, out = set(), []
    for f in folders():
        for p in sorted(f.glob("*.py")):
            if p.stem not in seen and not p.stem.startswith(("_", "helpers", "novaprinter")):
                seen.add(p.stem)
                out.append(p)
    return out


def _load(path: Path):
    if str(_NOVA) not in sys.path:
        sys.path.insert(0, str(_NOVA))
    spec = importlib.util.spec_from_file_location(f"bramble_plugin_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, path.stem)()           # qBittorrent's rule: class named like the file


def _size(v) -> int:
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    return parse_size(s)


def _int(v) -> int:
    try:
        return int(str(v).strip())
    except ValueError:
        return -1


class Plugin:
    def __init__(self, path: Path):
        self.path = path
        self.engine = _load(path)
        self.name = getattr(self.engine, "name", path.stem)

    def search(self, query: str) -> list[Result]:
        import novaprinter                      # the shim in _nova
        rows: list[dict] = []
        novaprinter.collect(rows)
        with contextlib.redirect_stdout(io.StringIO()):
            self.engine.search(urllib.parse.quote(query), "all")
        out = []
        for d in rows:
            name = str(d.get("name", "")).strip()
            if not name:
                continue
            out.append(Result(title=name, link=str(d.get("link", "")), source=self.name,
                              size=_size(d.get("size", 0)), seeders=_int(d.get("seeds", -1)),
                              quality=quality_of(name)))
            out[-1].page = str(d.get("desc_link", ""))
            out[-1].plugin = self
        return out

    def resolve(self, link: str) -> str:
        """Some plugins list a page and only find the magnet when asked (download_torrent)."""
        if link.startswith("magnet:") or link.lower().split("?")[0].endswith(".torrent"):
            return link
        fn = getattr(self.engine, "download_torrent", None)
        if fn is None:
            return link
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(link)
        said = buf.getvalue().strip().split()
        return said[0] if said else link


def load_all() -> tuple[list[Plugin], list[str]]:
    plugins, errors = [], []
    for p in found():
        try:
            plugins.append(Plugin(p))
        except Exception as e:
            errors.append(f"{p.stem}: could not load ({e})")
    return plugins, errors
