"""SETTINGS: subtitles, full screen, where the library and inbox are."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
                             QListWidget, QVBoxLayout, QWidget)

from .. import paths
from .common import Panel, button, label

SUB_MODES = [("full", "Full subtitles in my language"), ("forced", "Only foreign-language lines"),
             ("off", "Off")]
LANGS = [("eng", "English"), ("spa", "Spanish"), ("fre", "French"), ("ger", "German"),
         ("ita", "Italian"), ("por", "Portuguese"), ("jpn", "Japanese")]


class SettingsPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, settings):
        super().__init__()
        self.s = settings
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        play = Panel("Playing")
        form = QFormLayout()
        form.setSpacing(10)
        self.subs = QComboBox()
        for key, text in SUB_MODES:
            self.subs.addItem(text, key)
        self.subs.setCurrentIndex([k for k, _ in SUB_MODES].index(settings["subtitles"]))
        self.subs.currentIndexChanged.connect(lambda _: self._set("subtitles", self.subs.currentData()))
        self.lang = QComboBox()
        for key, text in LANGS:
            self.lang.addItem(text, key)
        codes = [k for k, _ in LANGS]
        self.lang.setCurrentIndex(codes.index(settings["subtitle_language"])
                                  if settings["subtitle_language"] in codes else 0)
        self.lang.currentIndexChanged.connect(lambda _: self._set("subtitle_language", self.lang.currentData()))
        self.full = QCheckBox("Open films full screen")
        self.full.setChecked(bool(settings["fullscreen_video"]))
        self.full.toggled.connect(lambda v: self._set("fullscreen_video", v))
        form.addRow(label("Subtitles", "dim"), self.subs)
        form.addRow(label("Language", "dim"), self.lang)
        form.addRow(label("", "dim"), self.full)
        play.body.addLayout(form)
        play.body.addStretch(1)

        lib = Panel("Library folders")
        lib.body.addWidget(label("Bramble always looks in MARROW on a plugged-in Hawthorn drive "
                                 f"and in {paths.local_marrow()}. Add any other folders here.",
                                 "faint", wrap=True))
        self.roots = QListWidget()
        lib.body.addWidget(self.roots, 1)
        row = QHBoxLayout()
        row.addWidget(button("Add folder…", self._add_root))
        row.addWidget(button("Remove", self._remove_root))
        row.addWidget(button(f"Make {paths.MARROW_NAME} here", self._make_local,
                             tip=f"Creates {paths.local_marrow()} with its category folders"))
        row.addStretch(1)
        lib.body.addLayout(row)

        inbox = Panel("Inbox")
        inbox.body.addWidget(label("New films, games and programs that land in this folder are "
                                   "offered for filing.", "faint", wrap=True))
        self.inbox_lbl = label("", "body", wrap=True, selectable=True)
        inbox.body.addWidget(self.inbox_lbl)
        inbox.body.addWidget(button("Choose folder…", self._choose_inbox))
        inbox.body.addStretch(1)
        info = Panel("Where Bramble keeps things")
        info.body.addWidget(label(
            f"Settings: {paths.config_dir()}\nCache: {paths.cache_dir()}\n"
            f"Prepared programs and the Windows-game setup: {paths.data_dir()}",
            "faint", wrap=True, selectable=True))
        info.body.addStretch(1)

        col1 = QVBoxLayout()
        col1.addWidget(play)
        col1.addWidget(inbox)
        col1.addWidget(info)
        lay.addLayout(col1, 1)
        lay.addWidget(lib, 1)
        self._refresh()

    def _set(self, key, value) -> None:
        self.s[key] = value
        self.changed.emit()

    def _refresh(self) -> None:
        self.roots.clear()
        for r in self.s["library_roots"]:
            self.roots.addItem(r)
        self.inbox_lbl.setText("\n".join(str(p) for p in self.s.inbox_folders()))

    def _add_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "A folder Bramble should look in")
        if d and d not in self.s["library_roots"]:
            self.s["library_roots"] = self.s["library_roots"] + [d]
            self._refresh()
            self.changed.emit()

    def _remove_root(self) -> None:
        it = self.roots.currentItem()
        if it:
            self.s["library_roots"] = [r for r in self.s["library_roots"] if r != it.text()]
            self._refresh()
            self.changed.emit()

    def _make_local(self) -> None:
        paths.ensure_library(paths.local_marrow())
        self.changed.emit()

    def _choose_inbox(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder to watch for new downloads",
                                             str(paths.downloads_dir()))
        if d:
            self.s["inbox_folders"] = [d]
            self._refresh()
            self.changed.emit()
