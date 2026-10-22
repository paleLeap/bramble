"""Small shared pieces of the window: panels, background work, messages."""
from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from .. import theme


class Panel(QFrame):
    """Slate's card: a flat panel with an uppercase title row."""

    def __init__(self, title: str = "", parent: QWidget | None = None, flat: bool = False):
        super().__init__(parent)
        self.setObjectName("panelFlat" if flat else "panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 10, 12, 12)
        self.body.setSpacing(8)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title = QLabel(title.upper())
        self.title.setObjectName("panelTitle")
        self.header.addWidget(self.title)
        self.header.addStretch(1)
        if title:
            self.body.addLayout(self.header)

    def set_title(self, title: str) -> None:
        self.title.setText(title.upper())


def label(text: str = "", name: str = "", wrap: bool = False, selectable: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    if selectable:
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def button(text: str, on_click: Callable | None = None, name: str = "", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class _Bridge(QObject):
    done = pyqtSignal(object, object)        # result, error
    progress = pyqtSignal(object)


class Worker:
    """Run fn in a thread; deliver progress and the result on the window's thread.

    fn receives a `progress(value)` callable as its only argument.
    """
    _live: set["Worker"] = set()

    def __init__(self, fn: Callable[[Callable[[Any], None]], Any],
                 on_done: Callable[[Any, Exception | None], None] | None = None,
                 on_progress: Callable[[Any], None] | None = None):
        self.bridge = _Bridge()
        if on_done:
            self.bridge.done.connect(on_done)
        if on_progress:
            self.bridge.progress.connect(on_progress)
        self.bridge.done.connect(lambda *_: Worker._live.discard(self))
        self.fn = fn
        Worker._live.add(self)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            result = self.fn(self.bridge.progress.emit)
            self.bridge.done.emit(result, None)
        except Exception as e:      # reported to the window, never swallowed
            e.trace = traceback.format_exc()   # type: ignore[attr-defined]
            self.bridge.done.emit(None, e)


class Popup(QDialog):
    """A themed dialog in Slate's style: raised background, title, text, buttons."""

    def __init__(self, parent: QWidget | None, title: str, text: str = "", width: int = 460):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.setStyleSheet(theme.STYLESHEET +
                           f"QDialog{{background:{theme.BG_RAISED};border:1px solid {theme.BORDER};}}"
                           f"QLabel{{background:transparent;}}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(10)
        head = label(title, "title")
        head.setStyleSheet("font-size:16px;font-weight:800;")
        self.lay.addWidget(head)
        if text:
            self.text = label(text, "body", wrap=True)
            self.lay.addWidget(self.text)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        self.result_value: Any = None

    def add_button(self, text: str, value: Any = None, primary: bool = False,
                   on_click: Callable | None = None) -> QPushButton:
        def clicked():
            if on_click:
                on_click()
                return
            self.result_value = value
            self.accept()
        b = button(text, clicked, "primary" if primary else "")
        self.buttons.addWidget(b)
        if primary:
            b.setDefault(True)
        return b

    def finish(self) -> None:
        self.lay.addLayout(self.buttons)

    def ask(self) -> Any:
        self.finish()
        self.exec()
        return self.result_value


def tell(parent: QWidget | None, title: str, text: str) -> None:
    p = Popup(parent, title, text)
    p.add_button("Okay.", True, primary=True)
    p.ask()


def confirm(parent: QWidget | None, title: str, text: str, yes: str = "Continue",
            no: str = "Cancel") -> bool:
    p = Popup(parent, title, text)
    p.add_button(no, False)
    p.add_button(yes, True, primary=True)
    return bool(p.ask())


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
