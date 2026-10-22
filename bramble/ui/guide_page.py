"""GUIDE: the Troubleshooting Guide, searchable, with buttons that fix things."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLineEdit, QSplitter, QTextBrowser, QTreeWidget,
                             QTreeWidgetItem, QWidget)

from .. import guide, theme
from .common import Panel, button, label

ROLE = Qt.ItemDataRole.UserRole


class GuidePage(QWidget):
    action_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split)
        left = Panel("Troubleshooting Guide")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Describe the problem: no sound, subtitles, BIOS…")
        self.search.textChanged.connect(lambda _: self._fill())
        left.body.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(10)
        self.tree.currentItemChanged.connect(lambda cur, _p: cur and cur.data(0, ROLE) and
                                             self.show_topic(cur.data(0, ROLE)))
        left.body.addWidget(self.tree, 1)

        self.right = Panel("")
        self.heading = label("", "title", wrap=True)
        self.right.body.addWidget(self.heading)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        self.text.document().setDefaultStyleSheet(
            f"p, li {{ line-height: 150%; margin-bottom: 6px; }} code {{ color: {theme.TEXT_DIM}; }}"
            f" a {{ color: {theme.ACCENT}; }} b {{ color: {theme.TEXT}; }}")
        self.right.body.addWidget(self.text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.right.body.addLayout(self.actions)
        split.addWidget(left)
        split.addWidget(self.right)
        split.setSizes([360, 860])
        self._fill()
        self.show_topic(guide.TOPICS[0].id)

    def _fill(self) -> None:
        hits = guide.search(self.search.text())
        self.tree.blockSignals(True)
        self.tree.clear()
        first = None
        for section in guide.SECTIONS:
            in_sec = [t for t in hits if t.section == section]
            if not in_sec:
                continue
            sn = QTreeWidgetItem([section.upper()])
            sn.setFlags(Qt.ItemFlag.ItemIsEnabled)
            f = sn.font(0)
            f.setBold(True)
            f.setPointSizeF(max(7.0, f.pointSizeF() - 2))
            sn.setFont(0, f)
            self.tree.addTopLevelItem(sn)
            for t in in_sec:
                leaf = QTreeWidgetItem([t.title])
                leaf.setData(0, ROLE, t.id)
                sn.addChild(leaf)
                first = first or leaf
            sn.setExpanded(True)
        self.tree.blockSignals(False)
        if self.search.text() and first:
            self.tree.setCurrentItem(first)

    def show_topic(self, topic_id: str) -> None:
        t = guide.BY_ID.get(topic_id)
        if not t:
            return
        self.heading.setText(t.title)
        self.right.set_title(t.section)
        self.text.setHtml(t.body)
        while self.actions.count():
            w = self.actions.takeAt(0).widget()
            if w:
                w.deleteLater()
        for text, action in t.actions:
            self.actions.addWidget(button(text, lambda a=action: self.action_requested.emit(a),
                                          "primary" if action.startswith(("fix_", "show_")) else ""))
        self.actions.addStretch(1)
        # Keep the list in step when a topic is opened from elsewhere.
        it = self.tree.invisibleRootItem()
        for i in range(it.childCount()):
            sec = it.child(i)
            for j in range(sec.childCount()):
                if sec.child(j).data(0, ROLE) == topic_id:
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(sec.child(j))
                    self.tree.blockSignals(False)
