"""qBittorrent's search-plugin helpers, as plugins import them (from helpers import ...)."""
import gzip
import html
import io
import os
import re
import tempfile
import urllib.request

headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"}


def htmlentitydecode(s):
    return html.unescape(s)


def retrieve_url(url, custom_headers={}, request_data=None, ssl_context=None, unescape_html_entities=True):
    req = urllib.request.Request(url, request_data, {**headers, **custom_headers})
    with urllib.request.urlopen(req, timeout=20, context=ssl_context) as r:
        data = r.read()
        if r.info().get("Content-Encoding") == "gzip":
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
        charset = r.headers.get_content_charset() or "utf-8"
    text = data.decode(charset, "replace")
    return htmlentitydecode(text) if unescape_html_entities else text


def download_file(url, referer=None, ssl_context=None):
    req = urllib.request.Request(url, headers={**headers, **({"referer": referer} if referer else {})})
    with urllib.request.urlopen(req, timeout=30, context=ssl_context) as r:
        data = r.read()
    fd, path = tempfile.mkstemp(suffix=".torrent")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return f"{path} {url}"
