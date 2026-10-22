"""qBittorrent's novaprinter, as plugins import it. Results go to the caller's list
instead of stdout."""
import threading

# Results are filed under the plugin module that printed them (found from the call
# stack), so a plugin's own worker threads still reach the right list.
_sinks = {}
_lock = threading.Lock()


def collect(target, module=None):
    with _lock:
        _sinks[module] = target


def prettyPrinter(d):
    import inspect
    module = None
    for frame in inspect.stack()[1:6]:
        name = frame.frame.f_globals.get("__name__", "")
        if name.startswith("bramble_plugin_"):
            module = name
            break
    with _lock:
        items = _sinks.get(module)
    if items is not None:
        items.append(dict(d))


def anySizeToBytes(size_string):
    return size_string


# Newer qBittorrent plugins build their result as SearchResults(**fields) before printing.
SearchResults = dict
