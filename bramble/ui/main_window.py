"""Bramble's window: a header with page tabs, the pages, a status line.

    BRAMBLE   LIBRARY  INBOX  PROGRAMS  GUIDE  SETTINGS          ●  Refresh
    ------------------------------------------------------------------------
    (page)
    ------------------------------------------------------------------------
    status                                              drive · this PC
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QButtonGroup, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget,
                             QVBoxLayout, QWidget)

from .. import fetch, library, paths, system, theme, tools
from ..library import Item
from ..settings import Settings
from .common import Worker, button, confirm, label, tell
from .dialogs import DownloadDialog, FileItDialog
from .guide_page import GuidePage
from .inbox_page import InboxPage
from .library_page import LibraryPage
from .programs_page import ProgramsPage
from .settings_page import SettingsPage

PAGES = ["Library", "Inbox", "Programs", "Guide", "Settings"]


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.items: list[Item] = []
        self._scanning = False
        self.setWindowTitle("Bramble")
        self.setStyleSheet(theme.STYLESHEET)
        self.resize(1400, 860)
        self.setAcceptDrops(True)

        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)

        # header
        header = QWidget()
        header.setObjectName("headerBar")
        header.setFixedHeight(40)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 10, 0)
        hl.setSpacing(10)
        brand = label("BRAMBLE", "headerBrand")
        hl.addWidget(brand)
        hl.addSpacing(10)
        self.tabs = QButtonGroup(self)
        self.tabs.setExclusive(True)
        self.tab_buttons: dict[str, QPushButton] = {}
        for i, name in enumerate(PAGES):
            b = QPushButton(name.upper())
            b.setObjectName("pageTab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(f"{name} (F{i + 1})")
            self.tabs.addButton(b, i)
            self.tab_buttons[name] = b
            hl.addWidget(b)
            QShortcut(QKeySequence(f"F{i + 1}"), self, activated=lambda i=i: self.go(PAGES[i]))
        self.tabs.idClicked.connect(lambda i: self.go(PAGES[i]))
        hl.addStretch(1)
        self.health = label("●", "")
        self.health.setStyleSheet(f"color:{theme.TEXT_FAINT};font-size:14px;background:transparent;")
        hl.addWidget(self.health)
        self.refresh_btn = button("Refresh", self.rescan, "ghost", "Look for new files (F5 also works)")
        self.refresh_btn.setStyleSheet("font-size:11px;padding:3px 10px;")
        hl.addWidget(self.refresh_btn)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.rescan)
        outer.addWidget(header)

        # pages
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 10, 12, 10)
        self.stack = QStackedWidget()
        bl.addWidget(self.stack)
        outer.addWidget(body, 1)
        self.library = LibraryPage(settings)
        self.inbox = InboxPage(settings)
        self.programs = ProgramsPage(settings)
        self.guide = GuidePage()
        self.settings_page = SettingsPage(settings)
        for page in (self.library, self.inbox, self.programs, self.guide, self.settings_page):
            self.stack.addWidget(page)
        for page in (self.library, self.inbox):
            page.open_requested.connect(self.open_item)
            page.fix_requested.connect(self.handle_fix)
            page.file_requested.connect(self.file_item)
        self.programs.download_requested.connect(self.start_download)
        self.programs.install_requested.connect(self.start_install)
        self.guide.action_requested.connect(self.handle_action)
        self.settings_page.changed.connect(self.rescan)

        # status line
        bar = QWidget()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(26)
        sl = QHBoxLayout(bar)
        sl.setContentsMargins(14, 0, 14, 0)
        self.status = label("", "status")
        self.where = label("", "status")
        sl.addWidget(self.status, 1)
        sl.addWidget(self.where)
        outer.addWidget(bar)

        self.go("Library")
        self.timer = QTimer(self, interval=20000)
        self.timer.timeout.connect(lambda: self.rescan(quiet=True))
        self.timer.start()
        QTimer.singleShot(0, self.rescan)

    # --- pages ------------------------------------------------------------------
    def go(self, name: str) -> None:
        i = PAGES.index(name)
        self.stack.setCurrentIndex(i)
        self.tab_buttons[name].setChecked(True)
        if name == "Programs":
            self.programs.refresh()

    def say(self, text: str, level: str = "") -> None:
        color = {"bad": theme.DOWN, "warn": theme.WARN, "ok": theme.UP}.get(level, theme.TEXT_DIM)
        self.status.setStyleSheet(f"color:{color};background:transparent;font-size:11px;")
        self.status.setText(text)

    # --- scanning ---------------------------------------------------------------
    def rescan(self, quiet: bool = False) -> None:
        if self._scanning:
            return
        self._scanning = True
        if not quiet:
            self.say("Looking through the library…")
        settings = self.settings

        def work(_p):
            items = library.scan(settings)
            inbox = library.scan_inbox(settings, items)
            roots = library.library_roots(settings)
            players = [t for t in ("vlc", "mpv") if tools.find_all(t)]
            return items, inbox, roots, players

        Worker(work, lambda res, err: self._scanned(res, err, quiet))

    def _scanned(self, res, err, quiet: bool) -> None:
        self._scanning = False
        if err:
            self.say(f"Could not read the library: {err}", "bad")
            return
        items, inbox, roots, players = res
        self.items = items
        self.library.set_items(items, roots)
        self.inbox.set_items(inbox)
        n_in = len(inbox)
        self.tab_buttons["Inbox"].setText(f"INBOX  {n_in}" if n_in else "INBOX")
        drives = paths.find_drives()
        self.where.setText((f"drive: {drives[0]}" if drives else "drive: not plugged in")
                           + f"   ·   {system.os_label()}")
        ok = bool(players)
        self.health.setStyleSheet(f"color:{theme.UP if ok else theme.WARN};font-size:14px;"
                                  "background:transparent;")
        self.health.setToolTip("Ready to play films: " + ", ".join(players) if ok else
                               "No video player found yet: see PROGRAMS")
        if not quiet:
            self.say(f"{len(items)} things in the library" + (f", {n_in} new in Downloads" if n_in else "") + ".")

    # --- opening ------------------------------------------------------------------
    def open_item(self, item: Item, way_label: str | None = None) -> None:
        from .. import launcher, probe
        if item.busy and not confirm(self, "Still downloading",
                                     f"{item.title} is probably still downloading. It may stop or "
                                     "skip partway through. Open it anyway?", "Open anyway"):
            return
        settings = self.settings
        details = self.library.details if self.stack.currentWidget() is self.library else self.inbox.details
        known_pr = details.pr if details.item is item else None
        self.say(f"Opening {item.title}…")

        def work(progress):
            pr = known_pr
            if pr is None and item.kind in ("movie", "episode"):
                pr = probe.probe(item.path)
            ways = launcher.ways_for(item, settings, pr, progress)
            if way_label:
                if way_label == "This PC's default app":
                    ways = [launcher.Way(way_label, "default")]
                else:
                    ways = [w for w in ways if w.label == way_label] or ways
            return launcher.try_ways(item, ways, progress)

        def done(outcome, err):
            if err:
                self.say(f"Could not open {item.title}: {err}", "bad")
                return
            if outcome.ok:
                self.say(f"Opened {item.title} with {outcome.used}.", "ok")
                tool = outcome.used.split(" (")[0].lower()
                if tool in ("vlc", "mpv"):
                    lg = dict(self.settings["last_good"])
                    lg[item.kind] = tool
                    self.settings["last_good"] = lg
                if way_label:
                    self.settings.remember(item.key, way=outcome.used)
                details.show_attempts(item, outcome)
            else:
                self.say(f"{item.title} did not open. See the details panel for what was tried.", "bad")
                details.show_failure(item, outcome)

        Worker(work, done, lambda msg: self.say(str(msg)))

    # --- filing -------------------------------------------------------------------
    def file_item(self, item: Item) -> None:
        dlg = FileItDialog(self, item, self.settings)
        dlg.finish()
        if dlg.exec() and dlg.result_value:
            self.say(f"Filed {item.title} in {Path(dlg.result_value).parent}.", "ok")
            self.rescan()

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        from .. import kinds
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if not p.exists():
                continue
            if p.is_dir():
                it = library._folder_game(p, "Video Games", p.parent)
            else:
                it = library._file_item(p, None, p.parent)
            if it is None:
                tell(self, "Not something to file", f"Bramble does not know what {p.name} is.")
                continue
            it.category = kinds.CATEGORY_FOR_KIND.get(it.kind, "Other")
            self.file_item(it)

    # --- fixes, downloads, installs -----------------------------------------------
    def handle_fix(self, fx, item: Item | None) -> None:
        if fx.run:
            self.say(f"{fx.label}…")
            Worker(lambda _p: fx.run(), lambda res, err: self._fixed(fx.label, res, err))
        elif fx.guide:
            self.go("Guide")
            self.guide.show_topic(fx.guide)
        elif fx.download:
            self.start_download(fx.download)
        elif fx.install:
            self.start_install(fx.install)

    def _fixed(self, what: str, res, err) -> None:
        ok, msg = (False, str(err)) if err else res
        self.say(msg, "ok" if ok else "bad")
        tell(self, what if ok else f"{what}: did not work", msg)
        cur = self.library.details.item
        if cur:
            self.library.details.show_item(cur)

    def handle_action(self, action: str) -> None:
        if action == "fix_passthrough":
            Worker(lambda _p: system.fix_passthrough(),
                   lambda res, err: self._fixed("Send plain sound to the TV", res, err))
        elif action == "show_on_tv":
            d = system.idle_external_display()
            if not d:
                tell(self, "No dark TV found", "Bramble does not see a TV or monitor that is "
                     "plugged in but switched off. Check the cable and the TV's input.")
                return
            Worker(lambda _p: system.show_on_external(d),
                   lambda res, err: self._fixed("Show the picture on the TV", res, err))
        elif action == "open_bios":
            roots = library.library_roots(self.settings)
            if roots:
                bios = roots[0] / "Video Games" / "BIOS"
                bios.mkdir(parents=True, exist_ok=True)
                system.show_in_folder(bios / "x")
        elif action.startswith("download:"):
            self.start_download(action.split(":", 1)[1])
        elif action.startswith("install:"):
            self.start_install(action.split(":", 1)[1])
        elif action.startswith("page:"):
            self.go(action.split(":", 1)[1].capitalize())

    def _tools_destination(self) -> Path:
        for drive in paths.find_drives():
            dest = paths.drive_tools(drive)
            try:
                dest.mkdir(parents=True, exist_ok=True)
                probe_file = dest / ".bramble-write-test"
                probe_file.write_text("x")
                probe_file.unlink()
                return dest
            except OSError:
                continue
        return paths.local_tools()

    def start_download(self, tool_id: str) -> None:
        name = tools.TOOLS[tool_id].name if tool_id in tools.TOOLS else tool_id
        self.say(f"Looking for the newest {name}…")

        def done(res, err):
            if err:
                self.say(f"Could not look for {name}: {err}", "bad")
                return
            rel, errors = res
            if rel is None:
                tell(self, f"Could not find {name}",
                     "None of the download sites answered:\n" + "\n".join(errors[:4]) +
                     "\n\nCheck the internet connection and try again.")
                self.say(f"Could not find {name} online.", "bad")
                return
            have = fetch.carried_version(tool_id)
            if have and not fetch.is_newer(rel.version, have):
                tell(self, f"{name} is up to date",
                     f"The carried copy is {have}; the newest is {rel.version} ({rel.source}).")
                self.say(f"{name} is up to date.")
                return
            dlg = DownloadDialog(self, name, rel, have, self._tools_destination())
            dlg.finish()
            if dlg.exec() and dlg.result_value:
                self.say(f"Downloaded {dlg.result_value}.", "ok")
                self.programs.refresh()
                self.rescan(quiet=True)
            else:
                self.say("")

        Worker(lambda _p: fetch.latest(tool_id), done)

    def start_install(self, tool_id: str) -> None:
        t = tools.TOOLS[tool_id]
        cmd = system.install_command(t.install_hint_linux, t.install_hint_windows)
        if not cmd:
            tell(self, f"Cannot install {t.name} here",
                 "This PC has no package manager Bramble knows how to use.")
            return
        how = ("Linux will ask for this PC's password." if paths.IS_LINUX else
               "Windows will ask for permission.")
        if not confirm(self, f"Install {t.name} on this PC?",
                       f"{how} It needs the internet.\n\nCommand: {' '.join(cmd)}", "Install"):
            return
        self.say(f"Installing {t.name}…")

        def work(_p):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            return r.returncode, (r.stderr or r.stdout)[-600:]

        def done(res, err):
            if err:
                tell(self, f"{t.name} was not installed", str(err))
                return
            code, out = res
            if code == 0:
                self.say(f"{t.name} is installed.", "ok")
                self.programs.refresh()
                self.rescan(quiet=True)
                return
            hint = ""
            if "authentication agent" in out.lower() or code in (126, 127):
                hint = ("\n\nNo password window could be shown. Open a terminal and run:\n"
                        f"sudo {' '.join(cmd[1:]) if cmd[0] == 'pkexec' else ' '.join(cmd)}")
            tell(self, f"{t.name} was not installed", f"The installer stopped (code {code}).\n{out}{hint}")
            self.say(f"{t.name} was not installed.", "bad")

        Worker(work, done)
