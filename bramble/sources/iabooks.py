"""The Internet Archive's books (archive.org): libraries' scans of books out of copyright,
free to download as PDFs. Only the libraries' own scanning collections are searched,
never what members of the public upload. A book still in copyright that the Archive
lends (free, with an account) is offered as its page, to open or keep as a link.

(Open Library is the catalogue in front of these same scans, but its search often
takes longer than 15 seconds; the Archive's own answers in under one.)
"""
from __future__ import annotations

import json
import re

from . import Result, get, quote

SHOW = 8
LIBRARIES = ("americana", "toronto", "internetarchivebooks", "cdl", "europeanlibraries",
             "library_of_congress", "newyorkpubliclibrary", "duke_libraries")
LENDING = ("inlibrary", "printdisabled", "lendinglibrary")


def _author(creator) -> str:
    """"Stoker, Bram, 1847-1912" as a person would say it: "Bram Stoker"."""
    name = creator[0] if isinstance(creator, list) and creator else str(creator or "")
    name = re.sub(r",?\s*\d{3,4}\s*-\s*(\d{3,4})?\.?$", "", name).strip(" ,")
    parts = [p.strip() for p in name.split(",")]
    return f"{parts[1]} {parts[0]}" if len(parts) == 2 and parts[1] else name


class ArchiveBooks:
    name = "archive.org books"
    books = True

    def search(self, query: str) -> list[Result]:
        return self._free(query) or self._lent(query)

    def _lent(self, query: str) -> list[Result]:
        """Copies the Archive lends: a page to borrow it from, not a file."""
        words = re.sub(r"[()\":]", " ", query)
        q = f"title:({words}) AND mediatype:texts AND collection:(inlibrary)"
        url = (f"https://archive.org/advancedsearch.php?q={quote(q)}&fl[]=identifier&fl[]=title"
               f"&fl[]=creator&fl[]=year&sort[]=downloads+desc&rows=2&output=json")
        out = []
        for d in json.loads(get(url, timeout=8)).get("response", {}).get("docs", []):
            ident = d.get("identifier", "")
            if not ident:
                continue
            title = d.get("title") or ident
            title = str(title[0] if isinstance(title, list) else title)
            by, year = _author(d.get("creator")), d.get("year")
            page = f"https://archive.org/details/{ident}"
            out.append(Result(title=title + (f" — {by}" if by else "") + (f" ({year})" if year else ""),
                              link=page, source=self.name, quality="borrow", kind_hint="book",
                              page=page, borrow=True))
        return out

    def _free(self, query: str) -> list[Result]:
        # one request: the search itself says which books have a PDF (always named after the
        # book's identifier), so no book is looked into separately (the Archive turns away
        # a PC that asks too much at once)
        words = re.sub(r"[()\":]", " ", query)
        q = (f"title:({words}) AND mediatype:texts AND collection:({' OR '.join(LIBRARIES)})"
             f" AND -collection:({' OR '.join(LENDING)})")
        url = (f"https://archive.org/advancedsearch.php?q={quote(q)}&fl[]=identifier&fl[]=title"
               f"&fl[]=creator&fl[]=year&fl[]=format&sort[]=downloads+desc&rows={SHOW}&output=json")
        out = []
        for d in json.loads(get(url, timeout=8)).get("response", {}).get("docs", []):
            ident = d.get("identifier", "")
            formats = d.get("format") or []
            if not ident or not any(f in ("Text PDF", "Image Container PDF") for f in formats):
                continue
            title = d.get("title") or ident
            title = str(title[0] if isinstance(title, list) else title)
            by, year = _author(d.get("creator")), d.get("year")
            out.append(Result(title=title + (f" — {by}" if by else "") + (f" ({year})" if year else ""),
                              link=f"https://archive.org/download/{ident}/{ident}.pdf", source=self.name,
                              quality="PDF", kind_hint="book", page=f"https://archive.org/details/{ident}",
                              direct=True))
        return out


SOURCE = ArchiveBooks()
