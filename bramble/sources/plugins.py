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
import re
import sys
import urllib.parse
import urllib.request
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
            return ""                     # a page, and no way to turn it into a torrent
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                fn(link)
        except Exception:
            return ""
        said = buf.getvalue().strip().split()
        got = said[0] if said else ""
        if got.startswith("magnet:") or got.lower().endswith(".torrent") or Path(got).is_file():
            return got
        return ""                         # it answered with nothing usable


def load_all() -> tuple[list[Plugin], list[str]]:
    plugins, errors = [], []
    for p in found():
        try:
            plugins.append(Plugin(p))
        except Exception as e:
            errors.append(f"{p.stem}: could not load ({e})")
    return plugins, errors


# --- adding plugins from inside Bramble -------------------------------------------

def is_plugin_ref(text: str) -> bool:
    """A plugin file's address or path, as typed into the search box or dropped."""
    t = text.strip().strip('"').strip("'")
    return t.lower().split("?")[0].endswith(".py")


def _raw(url: str) -> str:
    # a GitHub page for a file -> the file itself
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return url


def install_folder() -> Path:
    """Where a new plugin goes: the drive Bramble runs from (so it travels), else this PC."""
    for d in paths.find_drives():
        f = d / "INNARDS" / "bramble" / "plugins"
        try:
            f.mkdir(parents=True, exist_ok=True)
            probe = f / ".bramble-write-test"
            probe.write_text("x")
            probe.unlink()
            return f
        except OSError:
            continue
    f = paths.config_dir() / "plugins"
    f.mkdir(parents=True, exist_ok=True)
    return f


def install(ref: str) -> str:
    """Fetch or copy a qBittorrent search plugin into the plugins folder. Returns the
    name it searches as. Raises ValueError with a plain reason if it is not one."""
    ref = ref.strip().strip('"').strip("'")
    if re.match(r"(?i)https?://", ref):
        url = _raw(ref)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Bramble/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            code = r.read().decode("utf-8", "replace")
        filename = Path(urllib.parse.urlparse(url).path).name
    else:
        src = Path(ref).expanduser()
        if not src.is_file():
            raise ValueError(f"{src.name} was not found.")
        code = src.read_text(encoding="utf-8", errors="replace")
        filename = src.name
    stem = Path(filename).stem
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stem):
        raise ValueError(f"{filename} does not have a plugin's name (letters, digits and _ only).")
    try:
        compile(code, filename, "exec")
    except SyntaxError as e:
        raise ValueError(f"{filename} is not a working Python file ({e.msg}, line {e.lineno}).")
    if not re.search(rf"^class\s+{re.escape(stem)}\b", code, re.M) or "def search" not in code:
        raise ValueError(f"{filename} is not a qBittorrent search plugin "
                         f"(it needs a class called {stem} with a search).")
    target = install_folder() / filename
    target.write_text(code, encoding="utf-8")
    try:
        return Plugin(target).name
    except Exception as e:
        target.unlink(missing_ok=True)
        raise ValueError(f"{filename} could not start: {e}")
