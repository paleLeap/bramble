"""The Internet Archive (archive.org): public-domain films, shows and music. Legal to
share. Not switched on unless listed in settings "sources".

Its torrents rarely have anyone sharing them and lean on the Archive's own web
servers, which aria2 does not use for multi-file torrents, so this source hands
over the direct link to the item's best video (or audio) file instead."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from . import Result, get, quote, quality_of

VIDEO = (".mp4", ".mkv", ".m4v", ".avi", ".mov", ".mpeg", ".mpg", ".ogv")
AUDIO = (".mp3", ".flac", ".ogg", ".m4a")


class Archive:
    name = "archive.org"

    def _best_file(self, ident: str) -> tuple[str, int] | None:
        meta = json.loads(get(f"https://archive.org/metadata/{ident}"))
        files = [f for f in meta.get("files", []) if f.get("source") in ("original", "derivative")]
        vids = [f for f in files if f.get("name", "").lower().endswith(VIDEO)]
        pool = vids or [f for f in files if f.get("name", "").lower().endswith(AUDIO)]
        if not pool:
            return None
        best = max(pool, key=lambda f: int(f.get("size") or 0))
        return (f"https://archive.org/download/{ident}/{quote(best['name'])}", int(best.get("size") or 0))

    def search(self, query: str) -> list[Result]:
        q = quote(f'title:({query}) AND mediatype:(movies OR audio)')
        url = (f"https://archive.org/advancedsearch.php?q={q}&fl[]=identifier&fl[]=title"
               f"&sort[]=downloads+desc&rows=8&output=json")
        docs = json.loads(get(url)).get("response", {}).get("docs", [])

        def one(d):
            ident = d.get("identifier")
            title = d.get("title") or ident
            title = title[0] if isinstance(title, list) else title
            try:
                best = self._best_file(ident)
            except Exception:
                return None
            if not best:
                return None
            link, size = best
            return Result(title=str(title), source=self.name, link=link, size=size,
                          quality=quality_of(str(title)))

        with ThreadPoolExecutor(max_workers=6) as pool:
            return [r for r in pool.map(one, docs) if r]


SOURCE = Archive()
