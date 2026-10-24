"""Project Gutenberg (gutenberg.org): over 70,000 books out of copyright, free to download.
It offers EPUBs, not PDFs, so its books come after any PDF from the other free libraries.
Searched for books only, through its own catalogue feed (OPDS).
"""
from __future__ import annotations

import html
import re

from . import Result, get, quote

SHOW = 6
ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)


class Gutenberg:
    name = "Project Gutenberg"
    books = True

    def search(self, query: str) -> list[Result]:
        feed = get(f"https://www.gutenberg.org/ebooks/search.opds/?query={quote(query)}", timeout=8)
        out = []
        for entry in ENTRY.findall(feed):
            m = re.search(r"<id>https?://www\.gutenberg\.org/ebooks/(\d+)\.opds</id>", entry)
            if not m:
                continue                         # an author or a subject, not a book
            number = m.group(1)
            title = re.search(r"<title>(.*?)</title>", entry, re.S)
            by = re.search(r'<content type="text">(.*?)</content>', entry, re.S)
            name = html.unescape(title.group(1).strip()) if title else f"Book {number}"
            if by and by.group(1).strip():
                name += " — " + html.unescape(by.group(1).strip())
            out.append(Result(title=name, link=f"https://www.gutenberg.org/ebooks/{number}.epub3.images",
                              source=self.name, quality="EPUB", kind_hint="book",
                              page=f"https://www.gutenberg.org/ebooks/{number}", direct=True))
            if len(out) >= SHOW:
                break
        return out


SOURCE = Gutenberg()
