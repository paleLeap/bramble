"""qBittorrent's novaprinter, as plugins import it. Results go to the caller's list
instead of stdout."""
import threading

_sink = threading.local()


def collect(target):
    _sink.items = target


def prettyPrinter(d):
    items = getattr(_sink, "items", None)
    if items is not None:
        items.append(dict(d))


def anySizeToBytes(size_string):
    return size_string
