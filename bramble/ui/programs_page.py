"""PROGRAMS: what Bramble can open things with, here and on the drive."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from .. import fetch, paths, system, theme, tools
from .common import Panel, Worker, button, label

COLS = ["Program", "Used for", "On this PC", "Carried by Bramble", "Newest", ""]


class ProgramsPage(QWidget):
    download_requested = pyqtSignal(str)       # tool id
    install_requested = pyqtSignal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.newest: dict[str, str] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        panel = Panel("Programs")
        lay.addWidget(panel)
        self.check_btn = button("Check for newer versions", self.check_all,
                                tip="Asks each program's download sites; downloads nothing")
        panel.header.addWidget(self.check_btn)
        self.intro = label("", "faint", wrap=True)
        panel.body.addWidget(self.intro)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([c.upper() for c in COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in (0, 2, 3, 4, 5):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(44)
        panel.body.addWidget(self.table, 1)
        self.status = label("", "faint", wrap=True)
        panel.body.addWidget(self.status)

    def refresh(self) -> None:
        drives = paths.find_drives()
        where = (f"Carried programs come from {paths.drive_tools(drives[0])}" if drives else
                 "The Hawthorn drive is not plugged in; carried programs come from "
                 f"{paths.local_tools()} if Bramble downloaded any.")
        self.intro.setText(f"{system.os_label()}.  {where}")
        Worker(lambda _p: self._gather(), lambda rows, err: self._fill(rows or []))

    def _gather(self) -> list[tuple]:
        rows = []
        for t in tools.TOOLS.values():
            if paths.IS_WINDOWS and t.id in ("proton", "wine"):
                continue
            pc = tools.find_on_pc(t)
            car = tools.find_carried(t)
            rows.append((t, pc, car, fetch.carried_version(t.id)))
        return rows

    def _fill(self, rows) -> None:
        self.table.setRowCount(len(rows))
        for r, (t, pc, car, ver) in enumerate(rows):
            self._cell(r, 0, t.name, bold=True)
            self._cell(r, 1, t.purpose, dim=True)
            self._cell(r, 2, ("● " + (str(pc.path) if pc.path else " ".join(pc.argv))) if pc else "not installed",
                       color=theme.UP if pc else theme.TEXT_FAINT)
            carried_txt = ("● " + (ver or "yes") + f"  ({car.where})") if car else "not carried"
            self._cell(r, 3, carried_txt, color=theme.UP if car else theme.TEXT_FAINT)
            self._cell(r, 4, self.newest.get(t.id, ""), dim=True)
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(4, 4, 4, 4)
            row.setSpacing(6)
            has_source = t.id in fetch.SOURCES and (t.carried_windows if paths.IS_WINDOWS else t.carried_linux)
            if has_source:
                row.addWidget(button("Update…" if car else "Download…",
                                     lambda tid=t.id: self.download_requested.emit(tid),
                                     tip="Shows what it found first; nothing downloads until you say so"))
            if not pc and system.install_command(t.install_hint_linux, t.install_hint_windows):
                row.addWidget(button("Install on this PC", lambda tid=t.id: self.install_requested.emit(tid),
                                     tip="Asks for this PC's password" if paths.IS_LINUX else ""))
            row.addStretch(1)
            self.table.setCellWidget(r, 5, box)

    def _cell(self, r, c, text, bold=False, dim=False, color=None):
        it = QTableWidgetItem(text)
        it.setToolTip(text)
        if color or dim:
            from PyQt6.QtGui import QColor
            it.setForeground(QColor(color or theme.TEXT_DIM))
        if bold:
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        self.table.setItem(r, c, it)

    def check_all(self) -> None:
        self.check_btn.setEnabled(False)
        self.status.setText("Asking the download sites…")

        def work(progress):
            out = {}
            for tid in fetch.SOURCES:
                rel, errs = fetch.latest(tid)
                out[tid] = (rel.version if rel else "could not check") + (
                    f"  ({rel.source})" if rel else "")
                progress(tid)
            return out

        def done(res, err):
            self.check_btn.setEnabled(True)
            if err:
                self.status.setText(f"Could not check: {err}")
                return
            self.newest = res
            self.status.setText("Checked. Press Update… on a program to see what it would download.")
            self.refresh()

        Worker(work, done, lambda tid: self.status.setText(f"Asking the download sites… {tid}"))
