"""Where the search box looks. Each source is one small module in this folder
with a SOURCE object: a name and a search(query) that returns Results.

The owner chooses the sources (settings "sources": module names). Bramble asks
them all at once, merges what they return, and lists the best-shared first.

Books: a search with "book" (or "pdf", "epub", "novel" ...) in it asks the free
libraries first (sources with books = True, on unless switched off), PDFs before
EPUBs; only when they have nothing to download are the torrent sites asked (for
the book's file), after any library that lends it. Every other search asks the
libraries too, and shows a book whose title is close to what was typed.
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
    site: bool = False          # a whole site's search page, opened in the browser
    plugin: object = None       # the plugin that found it (to turn a page into a magnet)
    direct: bool = False        # a plain file to download (a free library's PDF), no torrent
    borrow: bool = False        # a library's page to borrow it from (open it, or keep the link)


@dataclass
class Outcome:
    results: list[Result] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    note: str = ""              # said above the results ("No free copy ...")
    free: bool = False          # a book found in the free libraries: no torrent sites asked


BOOK_WORDS = {"book", "books", "ebook", "ebooks", "e-book", "pdf", "epub", "novel", "audiobook"}


def book_query(query: str) -> str | None:
    """A search for a book: what to look for, without the word that said so. None otherwise."""
    words = query.split()
    rest = [w for w in words if w.lower().strip(".,") not in BOOK_WORDS]
    return " ".join(rest) if rest and len(rest) < len(words) else None


def torrent_query(query: str) -> str:
    """What the torrent sites are asked. For a book, its name and the file wanted ("lord of
    the flies pdf"): most sites have no books category, and the name alone finds the films."""
    book = book_query(query)
    if book is None:
        return query
    fmt = next((w for w in query.lower().split() if w in ("pdf", "epub")), "pdf")
    return f"{book} {fmt}"


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


def catalog(settings) -> list[tuple[str, str, bool]]:
    """Every search source Bramble knows, for the leaf's list: (key, name, on).
    Free libraries come first and are on unless switched off; other built-in sources are
    off unless chosen; plugins are on unless switched off."""
    from . import plugins
    off = set(settings["sources_off"])
    rows = []
    for n in book_sources():
        rows.append(("books:" + n, load(n).name, "books:" + n not in off))
    for n in available():
        try:
            if n not in book_sources():
                rows.append(("builtin:" + n, load(n).name, n in settings["sources"]))
        except Exception:
            continue
    for site in settings["sites"]:
        rows.append(("site:" + site["name"], site["name"], "site:" + site["name"] not in off))
    for path in plugins.found():
        try:
            m = re.search(r"""^\s*name\s*=\s*["']([^"']+)["']""", path.read_text(errors="replace"), re.M)
        except OSError:
            m = None
        rows.append((path.stem, m.group(1) if m else path.stem, path.stem not in off))
    return rows


def book_sources() -> list[str]:
    """The free libraries, PDFs first (their order in the leaf and in the results)."""
    found = []
    for n in available():
        try:
            if getattr(load(n), "books", False):
                found.append(n)
        except Exception:
            continue
    return sorted(found, key=lambda n: (n != "iabooks", n))


MARK = "bramble"


def site_from_address(address: str) -> dict:
    """A site's search page, searched there for the word "bramble", as a site to open.
    Raises ValueError with a plain reason."""
    a = address.strip()
    parts = urllib.parse.urlsplit(a)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("That is not a web address.")
    if MARK not in a.lower():
        raise ValueError(f'Search that site for the word "{MARK}" first, then paste the address '
                         "of its results page.")
    name = parts.netloc.lower().removeprefix("www.")
    return {"name": name, "url": a}


def site_link(site: dict, query: str) -> str:
    """The site's search page for `query`: its own address with the query where "bramble" was."""
    url = site["url"]
    i = url.lower().find(MARK)
    in_query = "?" in url[:i]
    q = urllib.parse.quote_plus(query) if in_query else urllib.parse.quote(query)
    return url[:i] + q + url[i + len(MARK):]


def site_results(query: str, sites: list[dict], off: set) -> list[Result]:
    return [Result(title=s["name"], link=site_link(s, query), source="site", page=site_link(s, query),
                   site=True)
            for s in sites if "site:" + s["name"] not in off]


def search(query: str, names: list[str], off: set | None = None) -> Outcome:
    """Ask every chosen built-in source and every plugin found (and not switched off),
    all at once. A book: the free libraries first, the torrent sites only if they have
    nothing."""
    from . import plugins
    off = off or set()
    book = book_query(query)
    if book is not None:
        libraries = [load(n) for n in book_sources() if "books:" + n not in off]
        out = _ask(libraries, book)
        lent = [r for r in out.results if r.borrow and _names_it(r, book)][:2]
        out.results = [r for r in out.results if not r.borrow and _names_it(r, book)]
        if out.results:
            # PDFs first (EPUBs if that is what was asked for), each library's best match first,
            # and always a few of the other kind in view
            first = "EPUB" if "epub" in query.lower().split() else "PDF"
            uniq = _unique(out.results)
            out.results = ([r for r in uniq if r.quality == first][:5]
                           + [r for r in uniq if r.quality != first][:3])
            out.free = True
            return out
        found, errs = plugins.load_all(skip=off)
        torrents = _ask(found, torrent_query(query), cat="books")
        torrents.errors = out.errors + errs + torrents.errors
        torrents.results = lent + _best(torrents.results)
        if not libraries:
            said = "The free libraries are switched off"
        elif len(out.errors) >= len(libraries):
            said = "The free libraries did not answer"      # not the same as having no copy
        elif lent:
            said = "No free copy to download; the Internet Archive lends it (open it, or save the link)"
        else:
            said = "No free copy in the free libraries"
        torrents.note = f"{said}; from the torrent sites:" if found else f"{said}."
        if not found and not torrents.results:
            torrents.note = f"{said}, and no torrent sites are set up."
        return torrents

    engines, load_errors = [], []
    for n in names:
        try:
            engines.append(load(n))
        except Exception as e:
            load_errors.append(f"{n}: {e}")
    found, errs = plugins.load_all(skip=off)
    libraries = [load(n) for n in book_sources() if "books:" + n not in off]
    out = _ask(engines + found + libraries, query)
    out.errors = load_errors + errs + [e for e in out.errors
                                       if not any(e.startswith(lib.name + ":") for lib in libraries)]
    # a book whose title is close to what was typed ("lord of the flies"), beside the rest
    books = [r for r in out.results if r.kind_hint == "book" and _close(r, query)][:2]
    rest = [r for r in out.results if r.kind_hint != "book"]
    if not engines and not found and not books:
        out.errors.append("No search sources are set up yet.")
        out.results = []
        return out
    best = _best(rest)
    pages = [r for r in best if r.site]
    out.results = pages + books + [r for r in best if not r.site]
    return out


def _ask(engines: list, query: str, cat: str = "all") -> Outcome:
    """Every engine at once; one broken site never spoils the others."""
    out = Outcome()
    if not engines:
        return out

    def one(engine):
        try:
            if cat != "all" and hasattr(engine, "path"):           # a qBittorrent plugin
                return engine.search(query, cat), None
            return engine.search(query), None
        except Exception as e:
            return [], f"{getattr(engine, 'name', 'a source')}: {_plainly(e)}"

    with ThreadPoolExecutor(max_workers=max(1, len(engines))) as pool:
        for results, err in pool.map(one, engines):
            out.results.extend(results or [])
            if err:
                out.errors.append(err)
    return out


SMALL_WORDS = {"a", "an", "the", "of", "and", "in", "on", "to", "for", "by", "with", "at", "from"}


def _names_it(r: Result, query: str) -> bool:
    """The book's title or author has every word that matters in the search. Libraries
    also match inside the text, which finds books that only mention the words."""
    have = set(re.findall(r"\w+", r.title.lower()))
    want = [w for w in re.findall(r"\w+", query.lower()) if w not in SMALL_WORDS]
    return all(w in have for w in want)


def _close(r: Result, query: str) -> bool:
    """A library's book whose title is what was typed, give or take a subtitle."""
    title = r.title.split(" — ")[0]
    have = {w for w in re.findall(r"\w+", title.lower()) if w not in SMALL_WORDS}
    want = {w for w in re.findall(r"\w+", query.lower()) if w not in SMALL_WORDS}
    return bool(want) and want <= have and len(have) <= len(want) + 2


def _unique(results: list[Result]) -> list[Result]:
    seen, uniq = set(), []
    for r in results:
        key = re.sub(r"\W+", "", r.title.lower())
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def _best(results: list[Result]) -> list[Result]:
    """A site that turned the search away stands as its own search page, first; then the
    best shared, then the bigger (usually better quality)."""
    pages = [r for r in results if r.site]
    rest = sorted((r for r in results if not r.site),
                  key=lambda r: (-(r.seeders if r.seeders >= 0 else 0), -r.size))
    return pages + _unique(rest)[:SHOW]


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
    if "Connection reset" in text or "Errno 104" in text:
        return "the site broke off the connection (it may be down, or turning programs away)"
    if "Connection refused" in text or "Errno 111" in text:
        return "the site is not taking connections (it may be down)"
    if "Name or service not known" in text or "getaddrinfo" in text:
        return "the site could not be found (it may have moved, or there is no internet)"
    return text
