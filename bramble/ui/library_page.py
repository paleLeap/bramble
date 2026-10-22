"""LIBRARY: categories on the left, the list in the middle, the chosen item on the right."""
from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QPushButton, QScrollArea, QSplitter,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import checks, kinds, launcher, paths, probe, system, theme
from ..library import Item
from .common import Panel, Worker, button, human_size, label

RECENT = "Recently added"
ROLE = Qt.ItemDataRole.UserRole

PLAY_WORD = {"movie": "Play", "episode": "Play", "music": "Play", "rom": "Play game",
             "game_windows": "Play game", "game_linux": "Play game", "program": "Run",
             "installer": "Install", "archive": "Open", "image": "Open", "document": "Open",
             "other": "Open"}


class IssueCard(QFrame):
    def __init__(self, issue: checks.Issue, on_fix):
        super().__init__()
        self.setObjectName({"bad": "issueBad", "warn": "issue"}.get(issue.level, "issueInfo"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 10)
        lay.setSpacing(5)
        t = label(issue.title, wrap=True)
        t.setStyleSheet("font-weight:700;background:transparent;")
        lay.addWidget(t)
        d = label(issue.detail, "dim", wrap=True, selectable=True)
        d.setStyleSheet("background:transparent;")
        lay.addWidget(d)
        if issue.fixes:
            row = QHBoxLayout()
            row.setSpacing(6)
            for fx in issue.fixes:
                b = button(fx.label, lambda fx=fx: on_fix(fx))
                if fx.asks_password:
                    b.setToolTip("Asks for this PC's password")
                row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)


class Details(Panel):
    """The chosen item: what it is, Play, Open with, and anything in the way."""
    open_requested = pyqtSignal(object, object)        # item, way label (or None)
    fix_requested = pyqtSignal(object, object)         # Fix, item
    file_requested = pyqtSignal(object)

    def __init__(self, settings):
        super().__init__("Details")
        self.settings = settings
        self.item: Item | None = None
        self.pr: probe.Probe | None = None
        self.title = label("Nothing chosen", "title", wrap=True)
        self.sub = label("Pick something from the list.", "subtitle", wrap=True)
        self.facts = label("", "dim", wrap=True)
        self.where = label("", "faint", wrap=True, selectable=True)
        for w in (self.title, self.sub, self.facts, self.where):
            self.body.addWidget(w)
        row = QHBoxLayout()
        self.play = button("Play", lambda: self.item and self.open_requested.emit(self.item, None),
                           "primary")
        self.play.setMinimumHeight(34)
        self.play.setMinimumWidth(130)
        self.with_btn = QPushButton("Open with ▾")
        self.with_btn.clicked.connect(self._open_with_menu)
        self.folder_btn = button("Show in folder", lambda: self.item and system.show_in_folder(
            self.item.path))
        self.file_btn = button("File it…", lambda: self.item and self.file_requested.emit(self.item))
        for b in (self.play, self.with_btn, self.folder_btn, self.file_btn):
            row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)
        self.attempt = label("", "faint", wrap=True)
        self.body.addWidget(self.attempt)

        self.issue_box = QVBoxLayout()
        self.issue_box.setSpacing(8)
        holder = QWidget()
        holder.setObjectName("issueHolder")
        holder.setLayout(self.issue_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(holder)
        self.body.addWidget(scroll, 1)
        self._set_enabled(False)

    def _set_enabled(self, on: bool) -> None:
        for b in (self.play, self.with_btn, self.folder_btn, self.file_btn):
            b.setEnabled(on)

    def show_item(self, item: Item | None, inbox: bool = False) -> None:
        self.item = item
        self.pr = None
        self.attempt.setText("")
        self._clear_issues()
        if item is None:
            self.title.setText("Nothing chosen")
            self.sub.setText("Pick something from the list.")
            self.facts.setText("")
            self.where.setText("")
            self._set_enabled(False)
            return
        self._set_enabled(True)
        self.file_btn.setVisible(inbox)
        self.play.setText(PLAY_WORD.get(item.kind, "Open"))
        self.title.setText(item.title if not item.episode else item.episode.show)
        bits = [kinds.KIND_LABEL.get(item.kind, "File")]
        if item.episode:
            bits.insert(0, item.display)
        if item.year:
            bits.append(item.year)
        if item.system:
            bits.append(item.system.name)
        if item.album:
            bits.append(item.album)
        self.sub.setText("  ·  ".join(bits))
        added = time.strftime("%d %b %Y", time.localtime(item.mtime)) if item.mtime else ""
        facts = [human_size(item.size)] + ([f"added {added}"] if added else [])
        if item.busy:
            facts.append(f"<span style='color:{theme.WARN}'>still downloading</span>")
        self.facts.setText("  ·  ".join(facts))
        self.where.setText(str(item.target))
        if item.kind in ("movie", "episode", "music"):
            self.facts.setText(self.facts.text() + "  ·  looking inside…")
            path = item.path
            Worker(lambda _p: probe.probe(path), lambda pr, err, it=item: self._probed(it, pr))
        else:
            self._refresh_issues()

    def _probed(self, item: Item, pr) -> None:
        if item is not self.item:
            return
        self.pr = pr
        txt = self.facts.text().replace("  ·  looking inside…", "")
        if pr and pr.ok:
            extra = []
            if pr.resolution:
                extra.append(pr.resolution + (" HDR" if pr.hdr else ""))
            if pr.duration:
                m = int(pr.duration // 60)
                extra.append(f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min")
            if pr.audio:
                a = pr.audio[0]
                ch = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(a["channels"], f"{a['channels']} ch")
                extra.append(f"{a['codec'].upper()} {ch}")
            subs = sorted({(s.language or "?").upper()[:3] for s in pr.subs})
            if subs:
                extra.append("subtitles: " + ", ".join(subs))
            elif item.sidecar_subs:
                extra.append("subtitles: beside the file")
            txt += "  ·  " + "  ·  ".join(extra)
        self.facts.setText(txt)
        self._refresh_issues()

    def _clear_issues(self) -> None:
        while self.issue_box.count():
            w = self.issue_box.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _refresh_issues(self) -> None:
        if not self.item:
            return
        item, pr = self.item, self.pr

        def work(_p):
            return checks.before_open(item, pr)
        Worker(work, lambda issues, err, it=item: self._show_issues(it, issues or []))

    def _show_issues(self, item: Item, issues: list[checks.Issue]) -> None:
        if item is not self.item:
            return
        self._clear_issues()
        for iss in issues:
            self.issue_box.addWidget(IssueCard(iss, lambda fx: self.fix_requested.emit(fx, self.item)))
        self.issue_box.addStretch(1)

    def show_failure(self, item: Item, outcome) -> None:
        if item is not self.item:
            return
        self._clear_issues()
        for iss in checks.after_failure(item, outcome):
            self.issue_box.addWidget(IssueCard(iss, lambda fx: self.fix_requested.emit(fx, self.item)))
        self.issue_box.addStretch(1)

    def show_attempts(self, item: Item, outcome) -> None:
        if item is not self.item:
            return
        failed = [a for a in outcome.attempts if not a.ok]
        if outcome.ok:
            msg = f"Opened with {outcome.used}."
            if failed:
                msg += " Tried first: " + "; ".join(f"{a.way} ({a.detail})" for a in failed)
            self.attempt.setText(msg)

    def _open_with_menu(self) -> None:
        if not self.item:
            return
        menu = QMenu(self)
        item = self.item
        for way in launcher.ways_for(item, self.settings, self.pr):
            act = menu.addAction(way.label if way.available else f"{way.label}  (unavailable)")
            act.setEnabled(way.available)
            if way.note:
                act.setToolTip(way.note)
            act.triggered.connect(lambda _=False, w=way.label: self.open_requested.emit(item, w))
        if item.exe is not None or item.kind in ("game_windows", "game_linux", "program"):
            menu.addSeparator()
            menu.addAction("Choose the program file…").triggered.connect(self._choose_exe)
        menu.addSeparator()
        menu.addAction("This PC's default app").triggered.connect(
            lambda: self.open_requested.emit(item, "This PC's default app"))
        menu.exec(self.with_btn.mapToGlobal(self.with_btn.rect().bottomLeft()))

    def _choose_exe(self) -> None:
        item = self.item
        if not item:
            return
        start = str(item.path if item.path.is_dir() else item.path.parent)
        f, _ = QFileDialog.getOpenFileName(self, "Which file starts it?", start)
        if f:
            item.exe = Path(f)
            self.settings.remember(item.key, exe=f)
            self.where.setText(f)


class LibraryPage(QWidget):
    open_requested = pyqtSignal(object, object)
    fix_requested = pyqtSignal(object, object)
    file_requested = pyqtSignal(object)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.items: list[Item] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split)

        left = Panel("Library")
        self.cats = QListWidget()
        self.cats.currentRowChanged.connect(lambda _: self._fill())
        left.body.addWidget(self.cats, 1)
        self.roots_lbl = label("", "faint", wrap=True)
        left.body.addWidget(self.roots_lbl)

        mid = Panel("")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.textChanged.connect(lambda _: self._fill())
        mid.body.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.currentItemChanged.connect(lambda cur, _p: self._chosen(cur))
        self.tree.itemActivated.connect(lambda it, _c: self._activated(it))
        mid.body.addWidget(self.tree, 1)
        self.empty = label("", "faint", wrap=True)
        mid.body.addWidget(self.empty)

        self.details = Details(settings)
        self.details.open_requested.connect(self.open_requested)
        self.details.fix_requested.connect(self.fix_requested)
        self.details.file_requested.connect(self.file_requested)

        split.addWidget(left)
        split.addWidget(mid)
        split.addWidget(self.details)
        split.setSizes([230, 560, 520])
        split.setStretchFactor(1, 1)

    def set_items(self, items: list[Item], roots: list[Path]) -> None:
        # Remembered program files for folder games.
        for it in items:
            exe = self.settings.recall(it.key).get("exe")
            if exe and Path(exe).exists():
                it.exe = Path(exe)
        self.items = items
        current = self.cats.currentItem().data(ROLE) if self.cats.currentItem() else RECENT
        self.cats.blockSignals(True)
        self.cats.clear()
        counts = defaultdict(int)
        for it in items:
            counts[it.category] += 1
        for name in [RECENT] + paths.CATEGORIES:
            n = len(items) if name == RECENT else counts.get(name, 0)
            li = QListWidgetItem(f"{name}" + (f"   {n}" if name != RECENT else ""))
            li.setData(ROLE, name)
            self.cats.addItem(li)
            if name == current:
                self.cats.setCurrentItem(li)
        if self.cats.currentRow() < 0:
            self.cats.setCurrentRow(0)
        self.cats.blockSignals(False)
        shown = [str(r) for r in roots if r.is_dir()]
        self.roots_lbl.setText("Looking in:\n" + "\n".join(shown) if shown else "")
        self._fill()

    def _category(self) -> str:
        cur = self.cats.currentItem()
        return cur.data(ROLE) if cur else RECENT

    def _fill(self) -> None:
        cat = self._category()
        words = self.search.text().lower().split()
        chosen = self.details.item.key if self.details.item else None
        self.tree.clear()
        pool = [i for i in self.items if cat == RECENT or i.category == cat]
        if words:
            pool = [i for i in pool if all(w in f"{i.title} {i.display} {i.path.name} "
                                           f"{i.system.name if i.system else ''}".lower() for w in words)]
        select = None
        if cat == RECENT:
            for it in sorted(pool, key=lambda i: i.mtime, reverse=True)[:60]:
                node = self._leaf(it, f"{it.title if not it.episode else it.episode.show + ' ' + it.display}")
                node.setText(0, node.text(0) + f"   ·  {it.category}")
                self.tree.addTopLevelItem(node)
                select = node if it.key == chosen else select
        elif cat == "TV Shows":
            shows: dict[str, dict[int, list[Item]]] = defaultdict(lambda: defaultdict(list))
            for it in pool:
                ep = it.episode
                shows[ep.show if ep else it.title][ep.season if ep else 0].append(it)
            for show in sorted(shows, key=str.lower):
                sn = QTreeWidgetItem([show])
                self.tree.addTopLevelItem(sn)
                for season in sorted(shows[show]):
                    se = QTreeWidgetItem([f"Season {season}" if season else "Other"])
                    sn.addChild(se)
                    eps = sorted(shows[show][season], key=lambda i: i.episode.number if i.episode else 0)
                    for it in eps:
                        leaf = self._leaf(it, it.display)
                        se.addChild(leaf)
                        select = leaf if it.key == chosen else select
                sn.setExpanded(len(shows) <= 3 or bool(words))
        elif cat in ("Video Games", "Music"):
            groups: dict[str, list[Item]] = defaultdict(list)
            for it in pool:
                if cat == "Music":
                    g = it.album or "Songs"
                elif it.system:
                    g = it.system.name
                else:
                    g = {"game_windows": "PC (Windows)", "game_linux": "Linux"}.get(it.kind, "Other")
                groups[g].append(it)
            for g in sorted(groups, key=str.lower):
                gn = QTreeWidgetItem([f"{g}   {len(groups[g])}"])
                self.tree.addTopLevelItem(gn)
                for it in sorted(groups[g], key=lambda i: i.title.lower()):
                    leaf = self._leaf(it, it.title)
                    gn.addChild(leaf)
                    select = leaf if it.key == chosen else select
                gn.setExpanded(True)
        else:
            for it in sorted(pool, key=lambda i: i.title.lower()):
                node = self._leaf(it, it.display)
                self.tree.addTopLevelItem(node)
                select = node if it.key == chosen else select
        if not pool:
            folder = cat if cat != RECENT else "the category folders"
            self.empty.setText(f"Nothing here yet. Put files in {folder} inside MARROW, or "
                               "file them from INBOX." if not words else "Nothing matches.")
            self.empty.show()
        else:
            self.empty.hide()
        if select:
            self.tree.setCurrentItem(select)

    def _leaf(self, it: Item, text: str) -> QTreeWidgetItem:
        node = QTreeWidgetItem([text])
        node.setData(0, ROLE, it)
        tip = str(it.target)
        if it.busy:
            node.setForeground(0, QColor(theme.WARN))
            tip += "\nStill downloading"
        node.setToolTip(0, tip)
        return node

    def _chosen(self, node: QTreeWidgetItem | None) -> None:
        it = node.data(0, ROLE) if node else None
        if it is not None or node is None:
            self.details.show_item(it)

    def _activated(self, node: QTreeWidgetItem) -> None:
        it = node.data(0, ROLE)
        if it is not None:
            self.open_requested.emit(it, None)
