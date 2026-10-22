"""Starting Bramble: one window per person, themed like Slate.

    python -m bramble              open the window
    python -m bramble --selftest   build the window off-screen, scan, exit 0 if all is well
    python -m bramble FILE...      open the window and offer to file these
"""
from __future__ import annotations

import getpass
import logging
import os
import sys
from pathlib import Path

from . import __version__, paths


def _log_setup() -> None:
    log_dir = paths.cache_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_dir / "bramble.log", level=logging.INFO,
                        format="%(asctime)s  %(levelname)-7s %(name)-14s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")


def selftest() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from . import library, tools
    from .settings import Settings
    from .ui.main_window import MainWindow
    app = QApplication(sys.argv)
    s = Settings()
    w = MainWindow(s)
    items = library.scan(s)
    found = {t: bool(tools.find_all(t)) for t in tools.TOOLS}
    print(f"bramble {__version__} selftest: window ok, {len(items)} library items, "
          f"programs: {', '.join(k for k, v in found.items() if v) or 'none'}")
    w.close()
    app.quit()
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        print(__version__)
        return 0
    if "--selftest" in args:
        return selftest()
    _log_setup()
    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QFont, QIcon
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("Bramble")
    app.setDesktopFileName("bramble")
    app.setFont(QFont("Inter", 10))
    icon = paths.PACKAGE_DIR / "ui" / "bramble.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    # One Bramble per person: a second launch brings the first one forward.
    key = f"bramble-{getpass.getuser()}"
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(300):
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    from .settings import Settings
    from .ui.main_window import MainWindow
    win = MainWindow(Settings())

    def raise_window():
        conn = server.nextPendingConnection()
        if conn:
            conn.readAll()
        win.showNormal()
        win.raise_()
        win.activateWindow()
    server.newConnection.connect(raise_window)

    win.show()
    files = [Path(a) for a in args if not a.startswith("-") and Path(a).exists()]
    if files:
        def offer():
            from PyQt6.QtCore import QMimeData, QUrl
            for f in files:
                from . import kinds, library
                it = (library._folder_game(f, "Video Games", f.parent) if f.is_dir()
                      else library._file_item(f, None, f.parent))
                if it:
                    it.category = kinds.CATEGORY_FOR_KIND.get(it.kind, "Other")
                    win.file_item(it)
        QTimer.singleShot(400, offer)
    logging.info("bramble %s started from %s", __version__, paths.APP_DIR)
    return app.exec()
