"""INBOX: new films, games and programs in Downloads, waiting to be filed."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QSplitter, QWidget

from .. import kinds
from ..library import Item
from .common import Panel, human_size, label
from .dialogs import _pretty, suggest_destination
from .library_page import Details

ROLE = Qt.ItemDataRole.UserRole


class InboxPage(QWidget):
    open_requested = pyqtSignal(object, object)
    fix_requested = pyqtSignal(object, object)
    file_requested = pyqtSignal(object)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split)
        left = Panel("New in Downloads")
        self.hint = label("Things that arrived in your Downloads folder. Choose one and press "
                          "File it… to put it in the library, or drop files onto this window.",
                          "faint", wrap=True)
        left.body.addWidget(self.hint)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda cur, _p: self.details.show_item(
            cur.data(ROLE) if cur else None, inbox=True))
        self.list.itemActivated.connect(lambda it: self.file_requested.emit(it.data(ROLE)))
        left.body.addWidget(self.list, 1)
        self.details = Details(settings)
        self.details.open_requested.connect(self.open_requested)
        self.details.fix_requested.connect(self.fix_requested)
        self.details.file_requested.connect(self.file_requested)
        split.addWidget(left)
        split.addWidget(self.details)
        split.setSizes([620, 600])

    def set_items(self, items: list[Item]) -> None:
        chosen = self.details.item.key if self.details.item else None
        self.list.clear()
        for it in items:
            dest = _pretty(suggest_destination(it, self.settings))
            busy = "  ·  still downloading" if it.busy else ""
            li = QListWidgetItem(f"{it.display}\n{kinds.KIND_LABEL.get(it.kind, 'File')}  ·  "
                                 f"{human_size(it.size)}{busy}  ·  goes to {dest}")
            li.setData(ROLE, it)
            li.setToolTip(str(it.path))
            self.list.addItem(li)
            if it.key == chosen:
                self.list.setCurrentItem(li)
        if not items:
            self.hint.setText("Nothing new in Downloads. Films, games and programs that arrive "
                              "there show up here.")
        if self.list.currentRow() < 0 and items:
            self.list.setCurrentRow(0)
        if not items:
            self.details.show_item(None)

    def count(self) -> int:
        return self.list.count()
