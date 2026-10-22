"""Where the search box looks. Each source is one small module in this folder
with a SOURCE object: a name and a search(query) that returns Results.

The owner chooses the sources (settings "sources": module names). Bramble asks
them all at once, merges what they return, and lists the best-shared first.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Bramble/1.0"}
SHOW = 6            # how many results the card lists


@dataclass
class Result:
    title: str
    link: str                   # magnet:, an http(s) .torrent, or a direct file link
    source: str
    size: int = 0               # bytes, 0 if unknown
    seeders: int = -1           # -1 if the source does not say
    quality: str = ""           # 1080p, 2160p ...
    kind_hint: str = ""         # "movie", "episode", "music", "game" if the source says
    page: str = ""              # the result's page on its site, when there is one
    plugin: object = None       # the plugin that found it (to turn a page into a magnet)


@dataclass
class Outcome:
    results: list[Result] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def get(url: str, timeout: float = 15) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def quote(q: str) -> str:
    return urllib.parse.quote(q)


SIZE = re.compile(r"(?i)([\d.,]+)\s*(B|KB|KiB|MB|MiB|GB|GiB|TB|TiB)\b")


def parse_size(text: str) -> int:
    m = SIZE.search(text or "")
    if not m:
        return 0
    n = float(m.group(1).replace(",", ""))
    unit = m.group(2).upper().replace("I", "")
    return int(n * {"B": 1, "KB": 1 << 10, "MB": 1 << 20, "GB": 1 << 30, "TB": 1 << 40}[unit])


def quality_of(title: str) -> str:
    m = re.search(r"(?i)\b(2160p|4k|1080p|720p|480p)\b", title)
    return m.group(1).lower().replace("4k", "2160p") if m else ""


def available() -> list[str]:
    import bramble.sources as pkg
    return [m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.name.startswith("_")]


def load(name: str):
    return importlib.import_module(f"bramble.sources.{name}").SOURCE


def search(query: str, names: list[str]) -> Outcome:
    """Ask every chosen built-in source and every plugin found, all at once."""
    from . import plugins
    out = Outcome()
    engines = []
    for n in names:
        try:
            engines.append(load(n))
        except Exception as e:
            out.errors.append(f"{n}: {e}")
    found, errs = plugins.load_all()
    engines += found
    out.errors += errs
    if not engines:
        out.errors.append("No search sources are set up yet.")
        return out

    def one(engine):
        try:
            return engine.search(query), None
        except Exception as e:            # one broken site never spoils the others
            return [], f"{getattr(engine, 'name', 'a source')}: {_plainly(e)}"

    with ThreadPoolExecutor(max_workers=max(1, len(engines))) as pool:
        for results, err in pool.map(one, engines):
            out.results.extend(results or [])
            if err:
                out.errors.append(err)
    # best shared first; then bigger (usually better quality) first
    out.results.sort(key=lambda r: (-(r.seeders if r.seeders >= 0 else 0), -r.size))
    seen, uniq = set(), []
    for r in out.results:
        key = re.sub(r"\W+", "", r.title.lower())
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    out.results = uniq[:SHOW]
    return out


def resolve(r: Result) -> str:
    """The link aria2 can download: some plugins list a page and find the magnet on request."""
    if r.plugin is not None:
        return r.plugin.resolve(r.link)
    return r.link


def _plainly(e: Exception) -> str:
    """A site's refusal in words, not an HTTP code."""
    text = str(e)
    code = getattr(e, "code", None)
    if code in (401, 403, 429, 503):
        return ("the site refused the search (it blocks programs that are not a web browser)"
                if code != 429 else "the site asked for fewer searches; try again later")
    if code == 404:
        return "the site no longer has a search page there (the plugin may be out of date)"
    if "timed out" in text.lower():
        return "the site did not answer in time"
    if "Name or service not known" in text or "getaddrinfo" in text:
        return "the site could not be found (it may have moved, or there is no internet)"
    return text
