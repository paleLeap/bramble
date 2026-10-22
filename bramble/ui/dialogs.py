"""Filing a file into the library, and confirming a download.

Both suggest a destination and let the person press Continue, or search for
another folder by typing part of its name.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QButtonGroup, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                             QProgressBar, QRadioButton, QVBoxLayout, QWidget)

from .. import kinds, paths
from ..library import Item
from .common import Popup, Worker, button, human_size, label


def _pretty(p: Path) -> str:
    """'MARROW › Video Games › SNES' (with the drive or home in front, faintly)."""
    parts = p.parts
    if paths.MARROW_NAME in parts:
        i = parts.index(paths.MARROW_NAME)
        return " › ".join(parts[i:])
    home = str(Path.home())
    s = str(p)
    return "~" + s[len(home):] if s.startswith(home) else s


class FolderSearch(QWidget):
    """Type part of a folder's name; matching folders under the given roots appear."""

    def __init__(self, roots: list[Path], on_pick):
        super().__init__()
        self.roots = roots
        self.on_pick = on_pick
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.box = QLineEdit()
        self.box.setPlaceholderText("Type part of a folder name…")
        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        lay.addWidget(self.box)
        lay.addWidget(self.list)
        self._folders: list[Path] | None = None
        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self._refresh)
        self.box.textChanged.connect(lambda _: self._timer.start())
        self.list.itemDoubleClicked.connect(self._picked)
        self.list.currentItemChanged.connect(lambda cur, _prev: cur and self.on_pick(
            Path(cur.data(Qt.ItemDataRole.UserRole)), final=False))
        Worker(lambda _p: self._collect(), lambda res, err: self._loaded(res))

    def _collect(self) -> list[Path]:
        out: list[Path] = []
        for root in self.roots:
            base_depth = len(root.parts)
            for dirpath, dirnames, _files in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith((".", "$"))
                               and d not in ("node_modules", "__pycache__", "System Volume Information")]
                p = Path(dirpath)
                out.append(p)
                if len(p.parts) - base_depth >= 4:
                    dirnames[:] = []
                if len(out) > 20000:
                    return out
        return out

    def _loaded(self, folders) -> None:
        self._folders = folders or []
        self._refresh()

    def _refresh(self) -> None:
        if self._folders is None:
            return
        words = self.box.text().lower().split()
        self.list.clear()
        shown = 0
        for f in self._folders:
            hay = str(f).lower()
            if all(w in hay for w in words):
                it = QListWidgetItem(_pretty(f))
                it.setToolTip(str(f))
                it.setData(Qt.ItemDataRole.UserRole, str(f))
                self.list.addItem(it)
                shown += 1
                if shown >= 300:
                    break

    def _picked(self, it: QListWidgetItem) -> None:
        self.on_pick(Path(it.data(Qt.ItemDataRole.UserRole)), final=True)

    def focus(self) -> None:
        self.box.setFocus()


def library_destinations() -> list[Path]:
    """Where filed things can go: each plugged-in drive's MARROW, then ~/MARROW."""
    roots = [paths.drive_marrow(d) for d in paths.find_drives()]
    roots.append(paths.local_marrow())
    return roots


def suggest_destination(item: Item, settings) -> Path:
    roots = library_destinations()
    root = roots[0]
    category = kinds.CATEGORY_FOR_KIND.get(item.kind, "Other")
    custom = settings["file_to"].get(category)
    if custom and Path(custom).exists():
        return Path(custom)
    dest = root / category
    for part in kinds.suggested_subfolder(Path(item.path.name), item.kind):
        dest = dest / part
    return dest


class FileItDialog(Popup):
    """'Save Hokum (2026) to Movies?'  [Search folders…]  [Cancel]  [Continue]"""

    def __init__(self, parent, item: Item, settings):
        self.item = item
        self.settings = settings
        self.dest = suggest_destination(item, settings)
        category = kinds.CATEGORY_FOR_KIND.get(item.kind, "Other")
        nice_cat = "Video Games" if category == "Video Games" else category
        super().__init__(parent, f"Save to the {nice_cat} folder?", width=560)
        self.lay.addWidget(label(f"{item.display}  ·  {kinds.KIND_LABEL.get(item.kind, 'File')}"
                                 f"  ·  {human_size(item.size)}", "dim", wrap=True))
        self.where = label("", "body", wrap=True, selectable=True)
        self.where.setStyleSheet("font-size:13px;font-weight:600;")
        self.lay.addWidget(self.where)
        self.full = label("", "faint", wrap=True, selectable=True)
        self.lay.addWidget(self.full)

        mode_row = QHBoxLayout()
        self.move_btn = QRadioButton("Move it")
        self.copy_btn = QRadioButton("Copy it (keeps the original, e.g. for seeding)")
        grp = QButtonGroup(self)
        grp.addButton(self.move_btn)
        grp.addButton(self.copy_btn)
        seeding = str(item.path).startswith(str(paths.downloads_dir()))
        (self.copy_btn if seeding else self.move_btn).setChecked(True)
        mode_row.addWidget(self.move_btn)
        mode_row.addWidget(self.copy_btn)
        mode_row.addStretch(1)
        self.lay.addLayout(mode_row)

        self.search = FolderSearch(library_destinations() + [Path.home()], self._pick)
        self.search.hide()
        self.lay.addWidget(self.search)

        self.bar = QProgressBar()
        self.bar.hide()
        self.lay.addWidget(self.bar)
        self.status = label("", "faint", wrap=True)
        self.lay.addWidget(self.status)

        self.search_btn = button("Search folders…", self._toggle_search)
        self.buttons.insertWidget(0, self.search_btn)
        self.add_button("Cancel", None)
        self.go = self.add_button("Continue", None, primary=True, on_click=self._go)
        if item.busy:
            self.status.setText("This file is still downloading. Filing it now may copy an "
                                "unfinished file.")
            self.status.setObjectName("warn")
        self._show_dest()

    def _show_dest(self) -> None:
        self.where.setText(_pretty(self.dest / self.item.path.name))
        self.full.setText(str(self.dest))

    def _toggle_search(self) -> None:
        vis = not self.search.isVisible()
        self.search.setVisible(vis)
        self.search_btn.setText("Hide search" if vis else "Search folders…")
        if vis:
            self.search.focus()
        self.adjustSize()

    def _pick(self, folder: Path, final: bool) -> None:
        self.dest = folder
        self.setWindowTitle("Save here?")
        self._show_dest()
        if final:
            self._go()

    def _go(self) -> None:
        src = self.item.path
        dest_dir = self.dest
        target = dest_dir / src.name
        if target.exists():
            self.status.setText(f"{target.name} is already there.")
            return
        copy = self.copy_btn.isChecked()
        self.go.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 1000)

        def work(progress):
            dest_dir.mkdir(parents=True, exist_ok=True)
            same_disk = _same_device(src, dest_dir)
            if not copy and same_disk:
                os.replace(src, target)
                return target
            _copy_with_progress(src, target, progress)
            if not copy:
                if src.is_dir():
                    shutil.rmtree(src)
                else:
                    src.unlink()
            return target

        def done(result, err):
            if err:
                self.bar.hide()
                self.status.setText(f"Could not file it: {err}")
                self.go.setEnabled(True)
                self.search_btn.setEnabled(True)
                return
            self.result_value = result
            self.accept()

        Worker(work, done, lambda frac: self.bar.setValue(int(frac * 1000)))


def _same_device(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _copy_with_progress(src: Path, dest: Path, progress) -> None:
    files = [src] if src.is_file() else [p for p in src.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files) or 1
    done = 0
    for f in files:
        out = dest if src.is_file() else dest / f.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".bramble-part")
        with open(f, "rb") as r, open(tmp, "wb") as w:
            while True:
                chunk = r.read(8 << 20)
                if not chunk:
                    break
                w.write(chunk)
                done += len(chunk)
                progress(done / total)
        shutil.copystat(f, tmp)          # keep the original date: a fresh one reads as "still downloading"
        os.replace(tmp, out)


class DownloadDialog(Popup):
    """Confirm a program download: what, from where, how big, saved where."""

    def __init__(self, parent, tool_name: str, release, have: str, dest: Path):
        verb = "A newer" if have else "Get"
        title = f"{verb} {tool_name}" + (" is available" if have else "")
        super().__init__(parent, title, width=540)
        self.release = release
        self.dest = dest
        lines = [f"<b>{tool_name} {release.version}</b> from <b>{release.source}</b>"]
        if release.size:
            lines.append(f"Size: {human_size(release.size)}")
        lines.append(f"This copy: {have}" if have else "Bramble does not carry it yet.")
        self.lay.addWidget(label("<br>".join(lines), "body", wrap=True))
        self.lay.addWidget(label("Saved to:", "dim"))
        self.where = label(str(dest), "body", wrap=True, selectable=True)
        self.where.setStyleSheet("font-weight:600;")
        self.lay.addWidget(self.where)
        self.lay.addWidget(label("Bramble looks for its programs there, on this PC and on the drive.",
                                 "faint", wrap=True))
        self.bar = QProgressBar()
        self.bar.hide()
        self.lay.addWidget(self.bar)
        self.status = label("", "faint", wrap=True)
        self.lay.addWidget(self.status)
        self.add_button("Not now", None)
        self.go = self.add_button("Continue", None, primary=True, on_click=self._go)

    def _go(self) -> None:
        from .. import fetch
        self.go.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)

        def work(progress):
            def b(done, total):
                progress(("bar", done, total))
            return fetch.install(self.release, self.dest, lambda s: progress(("say", s)), b)

        def on_progress(msg):
            if msg[0] == "say":
                self.status.setText(msg[1])
            else:
                _, done, total = msg
                if total:
                    self.bar.setRange(0, 1000)
                    self.bar.setValue(int(done / total * 1000))
                self.status.setText(f"{human_size(done)} of {human_size(total)}" if total else
                                    human_size(done))

        def done(result, err):
            if err:
                self.bar.hide()
                self.status.setText(f"Download failed: {err}")
                self.go.setEnabled(True)
                self.go.setText("Try again")
                return
            self.result_value = result
            self.accept()

        Worker(work, done, on_progress)
