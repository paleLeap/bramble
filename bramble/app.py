"""Starting Bramble: one window per person.

    python -m bramble              open the window
    python -m bramble --selftest   build the window off-screen, scan, exit 0 if all is well
"""
from __future__ import annotations

import getpass
import logging
import os
import sys

from . import __version__, paths


def _log_setup() -> None:
    log_dir = paths.cache_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / "bramble.log", level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(name)-14s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")


def _qt_app(argv):
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication
    # (Qt already follows the screen's Xft.dpi on Linux, so a 4K laptop gets 2x by itself.)
    if paths.IS_LINUX:
        # Hawthorn's window class, so the compositor gives Bramble the same
        # treatment: no forced opacity, rounding, shadow or blur (picom.conf).
        os.environ.setdefault("RESOURCE_NAME", "pale-lab-backdrop")
    app = QApplication(argv)
    app.setApplicationName("pale-lab-backdrop" if paths.IS_LINUX else "Bramble")
    app.setApplicationDisplayName("bramble")
    from .ui import paint
    paint.load_fonts()
    icon = paths.PACKAGE_DIR / "ui" / "bramble.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    return app


def selftest() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from . import library, tools
    from .settings import Settings
    from .ui.window import BrambleWindow
    app = _qt_app(sys.argv)
    s = Settings()
    w = BrambleWindow(s)
    w.show()
    app.processEvents()
    cats = library.categories(s)
    n = sum(len(library.scan_category(c)) for c in cats)
    found = {t: bool(tools.find_all(t)) for t in tools.TOOLS}
    print(f"bramble {__version__} selftest: window ok, {len(cats)} categories, {n} items, "
          f"programs: {', '.join(k for k, v in found.items() if v) or 'none'}")
    w.close()
    app.quit()
    return 0


def _magnets(claim: bool) -> int:
    """Make Bramble the PC's magnet-link handler, or give magnet links back."""
    from . import system
    from .settings import Settings
    s = Settings()
    if claim:
        ok, before = system.claim_magnet_links()
        if ok and before:
            s["magnet_handler_before"] = before
        print(f"magnet links now open in Bramble (before: {before or 'nothing'})" if ok
              else "could not make Bramble the magnet-link handler")
    else:
        ok = system.give_back_magnet_links(s["magnet_handler_before"])
        print(f"magnet links back to {s['magnet_handler_before']}" if ok else "nothing to give back")
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        print(__version__)
        return 0
    if "--selftest" in args:
        return selftest()
    if "--claim-magnets" in args or "--give-back-magnets" in args:
        return _magnets(claim="--claim-magnets" in args)
    _log_setup()
    # a magnet link or .torrent handed over by the browser (Bramble is the PC's magnet handler)
    link = next((a for a in args if a.startswith("magnet:") or a.lower().endswith(".torrent")), "")
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    app = _qt_app(sys.argv)

    # One Bramble per person: a second launch brings the first one forward.
    # (keyed on the settings folder too, so a copy run with other settings is its own)
    import hashlib
    key = f"bramble-{getpass.getuser()}-" + hashlib.sha1(str(paths.config_dir()).encode()).hexdigest()[:8]
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(300):
        sock.write(f"link {link}\n".encode() if link else b"show\n")
        sock.flush()
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    from .settings import Settings
    from .ui.window import BrambleWindow
    win = BrambleWindow(Settings())

    def heard():
        conn = server.nextPendingConnection()
        if not conn:
            return

        def read():
            said = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            if said.startswith("link "):
                win.handoff(said[5:])
            else:
                win.showNormal()
                win.raise_()
                win.activateWindow()
        conn.readyRead.connect(read)            # what it says may arrive after it connects
        if conn.bytesAvailable():
            read()
    server.newConnection.connect(heard)
    win.show()
    if link:
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(600, lambda: win.handoff(link))
    logging.info("bramble %s started from %s", __version__, paths.APP_DIR)

    # Whatever way Bramble ends (closed, killed, logged out), its torrent program ends too.
    from . import qbit
    import atexit
    import signal
    atexit.register(qbit.shutdown)
    app.aboutToQuit.connect(qbit.shutdown)
    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)):
        if sig is not None:
            signal.signal(sig, lambda *_: app.quit())
    # Python only sees signals between Qt events: wake it regularly so a SIGTERM lands.
    from PyQt6.QtCore import QTimer
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(500)
    return app.exec()
