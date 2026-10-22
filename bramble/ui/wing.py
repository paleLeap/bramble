"""The search windows, outside Bramble to its right, the way Hawthorn's console sits.

    bramble ............          ┌ results ────────┐
      + movies                    │ name            ├──┐
      + ...                       │   1080p · 2 GB  │  │
                                  └──┬──────────────┘  │
                         search ─────┘        ┌ download ┴──────┐
                                              │ name   34%  ... │
                                              └─────────────────┘

Search: a line grows out of Bramble at the search box, across then up, and the
results window unfolds out of that corner. Clicking a torrent: a line grows out
of the results window at that row, across then down, and the download window
unfolds below. Hawthorn's timeline (across, down/up, the card, its text), played
backwards to close.

All of it is drawn on one see-through window beside Bramble that follows it;
it only takes clicks where something is drawn.
"""
from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QRegion
from PyQt6.QtWidgets import QWidget

from .. import kinds, sources
from . import anim, look, paint

WING_W = 300             # how far the side windows reach right of Bramble
WING_EXTRA = 70          # and below it (the download window hangs a little lower)
GAP = 20                 # Hawthorn's CON_GAP
RES_W = 180              # Hawthorn's console is 170 wide; a little more for names
DL_W = 232
DL_SHIFT = 37            # the download window sits this far right of the results window
TIMELINE = (0.00, 0.28), (0.28, 0.52), (0.52, 1.00), (0.90, 1.12)   # across, turn, card, text
LINE_START = 6
ROW_H = 40               # a result: its name, and a faint line of facts under it


class Card:
    """One side window: its own Hawthorn timeline."""

    def __init__(self):
        self.tl = anim.Timeline(TIMELINE[3][1])
        self.close_hover = anim.Prop(0.0, look.COLOR_MS, look.css_ease)

    def part(self, i: int) -> float:
        return self.tl.part(TIMELINE[i])

    @property
    def shown(self) -> bool:
        return not self.tl.shut


class Wing(QWidget):
    def __init__(self, main):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle("bramble search")
        self.results_card = Card()
        self.dl_card = Card()
        self.query = ""
        self.results: list = []
        self.note = ""
        self.searching = False
        self.chosen = None               # the Result whose download is shown
        self.chosen_row_y = 0.0          # where its line leaves the results window
        self.job = None
        self.scroll = 0.0
        self.row_hover: dict[str, anim.Prop] = {}
        self.hover_key: str | None = None
        self.regions: list[tuple[QRectF, str, object]] = []
        self.dl_h = anim.Prop(84.0, look.GROW_MS)
        self.pasting = False             # the download window is asking for a magnet link
        from PyQt6.QtWidgets import QLineEdit
        from PyQt6.QtGui import QPalette
        self.paste = QLineEdit(self)
        self.paste.hide()
        self.paste.setFrame(False)
        self.paste.setPlaceholderText("Magnet Link.")
        self.paste.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {look.TEXT.name()}; border: none;"
            f" border-bottom: 1px solid {look.FAINT.name()}; padding: 0px; }}")
        pal = self.paste.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, look.FAINT)
        self.paste.setPalette(pal)
        self.paste.setFont(paint.font(look.NOTE_PX + 1))
        self.paste.returnPressed.connect(self._pasted)
        self.paste.textChanged.connect(lambda _t: self.update())
        self.choosing = False            # the list of torrent programs is open

    # --- where it sits ------------------------------------------------------------
    def follow(self) -> None:
        g = self.main.geometry()
        self.setGeometry(g.x() + g.width(), g.y(), WING_W, g.height() + WING_EXTRA)

    def canvas(self) -> QRectF:
        """Bramble's and this window's shared picture canvas, in this window's coordinates."""
        mw, mh = self.main.width(), self.main.height()
        return QRectF(-mw, 0, mw + WING_W, mh + WING_EXTRA)

    def results_rect(self) -> QRectF:
        h = self.main.height()
        top = look.MENU_TOP - 4
        bottom = max(top + 80, h - 74)
        return QRectF(GAP, top, RES_W, bottom - top)

    def dl_rect(self) -> QRectF:
        r = self.results_rect()
        return QRectF(r.left() + DL_SHIFT, r.bottom() + 22, DL_W, self.dl_h.value)

    def search_y(self) -> float:
        return self.main.height() - 24          # the middle of Bramble's search box

    # --- opening and closing -------------------------------------------------------
    def open_results(self, query: str) -> None:
        self.query = query
        self.results, self.note, self.searching = [], "", True
        self.scroll = 0.0
        self.close_download()
        self.follow()
        self.show()
        self.raise_()
        self.results_card.tl.open()

    def set_results(self, results: list, note: str) -> None:
        self.results, self.note, self.searching = results, note, False

    def close_results(self) -> None:
        self.close_download()
        self.results_card.tl.close()

    def open_download(self, result, row_y: float, job) -> None:
        self.chosen, self.chosen_row_y, self.job = result, row_y, job
        self.pasting = False
        self.paste.hide()
        self.dl_card.tl.open()

    def open_paste(self, result, row_y: float, prefill: str = "") -> None:
        """The download window, asking for the link the person copies from the site's page."""
        self.chosen, self.chosen_row_y, self.job = result, row_y, None
        self.pasting = True
        self.choosing = False
        self.paste.setText(prefill)
        self.dl_card.tl.open()

    def clipboard_changed(self) -> None:
        """A magnet link copied while the box is waiting goes straight into it (not started)."""
        if not self.pasting or self.paste.text().strip():
            return
        from PyQt6.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if text.startswith("magnet:?") or text.lower().split("?")[0].endswith(".torrent"):
            self.paste.setText(text)
            self.main.raise_()
            self.raise_()

    def _link_ok(self) -> bool:
        from .. import downloads
        link = self.paste.text().strip()
        return bool(link) and (link.startswith("magnet:?") or downloads.looks_like_link(link))

    def _pasted(self) -> None:
        if not self._link_ok():
            return
        link = self.paste.text().strip()
        self.pasting = False
        self.choosing = False
        self.paste.hide()
        r = self.chosen
        self.job = self.main.start_link(link, title=r.title if r else "",
                                        source_link=r.link if r else "",
                                        program=self.main.settings["torrent_program"])

    def _choose(self, program: str) -> None:
        self.main.settings["torrent_program"] = program
        self.choosing = False

    def close_download(self) -> None:
        self.pasting = False
        self.paste.hide()
        self.dl_card.tl.close()

    def moving(self) -> bool:
        return (self.results_card.tl.moving or self.dl_card.tl.moving or self.searching
                or self.dl_h.moving or (self.job is not None and not self.job.finished)
                or any(p.moving for p in self.row_hover.values())
                or self.results_card.close_hover.moving or self.dl_card.close_hover.moving)

    def tick(self) -> None:
        if not self.results_card.shown and not self.dl_card.shown:
            if self.isVisible():
                self.hide()
            return
        self.update()

    # --- drawing -------------------------------------------------------------------
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.regions = []
        mask = QRegion()
        mask = mask.united(self._paint_results(p))
        mask = mask.united(self._paint_download(p))
        p.end()
        # clicks only where something is drawn; the rest of this window lets them through
        self.setMask(mask if not mask.isEmpty() else QRegion(0, 0, 1, 1))

    def _lines(self, p: QPainter, pts: list[QPointF], across: float, turn: float) -> None:
        """Hawthorn's corner lines: the first stretch grows, then the second."""
        (x0, y0), (x1, y1), (x2, y2) = [(q.x(), q.y()) for q in pts]
        if across > 0.002:
            p.fillRect(QRectF(min(x0, x0 + (x1 - x0) * across), y0, abs(x1 - x0) * across, 1), look.LINE)
        if turn > 0.002:
            ye = y1 + (y2 - y1) * turn
            p.fillRect(QRectF(x1, min(y1, ye), 1, abs(ye - y1) + 1), look.LINE)

    def _card(self, p: QPainter, full: QRectF, corner: QPointF, c: float) -> QRectF:
        """The card opening out of the corner the lines point at; returns where it is now."""
        x0 = corner.x() + (full.left() - corner.x()) * c
        x1 = corner.x() + (full.right() - corner.x()) * c
        y0 = corner.y() + (full.top() - corner.y()) * c
        y1 = corner.y() + (full.bottom() - corner.y()) * c
        r = QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        p.save()
        p.setOpacity(c)
        for k in range(look.SHADOW, 0, -1):
            a = 0.05 * (1 - k / (look.SHADOW + 1))
            p.fillPath(paint.rounded(r.adjusted(-k, -k + 2, k, k + 2), look.RADIUS + k),
                       QColor(0, 0, 0, int(255 * a)))
        p.setClipPath(paint.rounded(r), Qt.ClipOperation.IntersectClip)
        self.main.bg.paint(p, r, look.GLASS_SCRIM, blur=True, canvas=self.canvas())
        p.restore()
        return r

    def _paint_results(self, p: QPainter) -> QRegion:
        card = self.results_card
        if not card.shown:
            return QRegion()
        full = self.results_rect()
        corner = QPointF(full.left() + 16, full.bottom())
        sy = self.search_y()
        self._lines(p, [QPointF(LINE_START, sy), QPointF(corner.x(), sy),
                        QPointF(corner.x(), full.bottom() + 6)],
                    card.part(0), card.part(1))
        c = card.part(2)
        # the window only shows what is inside its mask, so the lines are part of it
        region = QRegion(QRect(0, int(sy) - 2, int(corner.x()) + 3, 5)).united(
            QRegion(QRect(int(corner.x()) - 2, int(full.bottom()), 5, int(sy - full.bottom()) + 3)))
        if c <= 0.002:
            return region
        now = self._card(p, full, corner, c)
        region = region.united(QRegion(now.toAlignedRect()))
        t = card.part(3)
        if t > 0.002:
            p.save()
            p.setClipPath(paint.rounded(now), Qt.ClipOperation.IntersectClip)
            p.setOpacity(t)
            self._results_text(p, full, look.SLIDE * (1 - t), t > 0.5)
            p.restore()
        return region

    def _results_text(self, p: QPainter, full: QRectF, shift: float, live: bool) -> None:
        inner = full.adjusted(12, 12, -12, -12)
        # its own close mark, invisible until hovered
        cx = QRectF(full.right() - 24, full.top() + 2, 22, 22)
        hv = self.results_card.close_hover.value
        if hv > 0.01:
            paint.draw_text(p, cx.left() + 6, cx.top() + 3, "×", 13, look.alpha(look.TEXT, hv))
        if live:
            self.regions.append((cx, "close-results", self.close_results))
        p.save()
        p.setClipRect(inner.adjusted(-6, -4, 6, 4), Qt.ClipOperation.IntersectClip)
        x = inner.left() + shift
        y = inner.top() - self.scroll
        width = inner.width() - 14
        if self.searching:
            self._busy(p, x, y + 10)
        elif not self.results:
            for line in _wrap(self.note or "Nothing found.", look.NOTE_PX, width):
                paint.draw_text(p, x, y, line, look.NOTE_PX, look.FAINT)
                y += 16
        for r in self.results:
            key = "res:" + r.link
            hp = self.row_hover.setdefault(key, anim.Prop(0.0, look.COLOR_MS, look.css_ease))
            h = hp.value
            chosen = r is self.chosen and self.dl_card.tl.opening
            col = look.TEXT if chosen else look.mix(look.DIM, look.TEXT, h)
            title = paint.elide(r.title.replace("_", " "), look.LIST_PX, width)
            paint.draw_text(p, x, y + 2, title, look.LIST_PX, col, glow=h)
            facts = "  ·  ".join(b for b in (r.quality, _size(r.size),
                                             f"{r.seeders} seeders" if r.seeders >= 0 else "",
                                             r.source) if b)
            paint.draw_text(p, x, y + 20, paint.elide(facts, look.NOTE_PX, width), look.NOTE_PX,
                            look.FAINT)
            row = QRectF(x - 4, y, width + 8, ROW_H - 4)
            if live and inner.adjusted(-6, -4, 6, 4).intersects(row):
                self.regions.append((row, key, lambda r=r, ry=y + 10: self.main.choose_result(r, ry)))
            y += ROW_H
        self.content_h = y + self.scroll - inner.top()
        self.view_h = inner.height()
        p.restore()

    def _paint_download(self, p: QPainter) -> QRegion:
        card = self.dl_card
        if not card.shown or self.chosen is None:
            return QRegion()
        res = self.results_rect()
        full = self.dl_rect()
        bx = res.right() + 28
        corner = QPointF(bx, full.top())
        ry = max(res.top() + 10, min(res.bottom() - 10, self.chosen_row_y))
        self._lines(p, [QPointF(res.right() + 4, ry), QPointF(bx, ry), QPointF(bx, full.top() - 6)],
                    card.part(0), card.part(1))
        c = card.part(2)
        region = QRegion(QRect(int(res.right()), int(ry) - 2, int(bx - res.right()) + 3, 5)).united(
            QRegion(QRect(int(bx) - 2, int(ry), 5, int(full.top() - ry) + 3)))
        if c <= 0.002:
            return region
        now = self._card(p, full, corner, c)
        region = region.united(QRegion(now.toAlignedRect()))
        t = card.part(3)
        if t > 0.002:
            p.save()
            p.setClipPath(paint.rounded(now), Qt.ClipOperation.IntersectClip)
            p.setOpacity(t)
            self._download_text(p, full, look.SLIDE * (1 - t), t > 0.5)
            p.restore()
        return region

    def _download_text(self, p: QPainter, full: QRectF, shift: float, live: bool) -> None:
        job = self.job
        inner = full.adjusted(12, 12, -12, -12)
        x, y, width = inner.left() + shift, inner.top(), inner.width() - 14
        cx = QRectF(full.right() - 24, full.top() + 2, 22, 22)
        hv = self.dl_card.close_hover.value
        if hv > 0.01:
            paint.draw_text(p, cx.left() + 6, cx.top() + 3, "×", 13, look.alpha(look.TEXT, hv))
        if live:
            self.regions.append((cx, "close-download", self.close_download))
        title = kinds._tidy(self.chosen.title)
        paint.draw_text(p, x, y, paint.elide(title, look.LIST_PX, width), look.LIST_PX, look.TEXT)
        y += 22
        if self.pasting:
            # the box for the link copied from the site's page
            if live:
                self.paste.setGeometry(int(x), int(y), int(width), 20)
                if not self.paste.isVisible():
                    self.paste.show()
                    self.activateWindow()
                    self.paste.setFocus()
            elif self.paste.isVisible():
                self.paste.hide()
            y += 30
            if self._link_ok():
                # it grows a little: which program will download it, and a way to change that
                names = {"qbittorrent": "qBittorrent", "aria2": "aria2"}
                prog = self.main.settings["torrent_program"]
                q = f"Download with {names.get(prog, prog)}?"
                hv = 1.0 if self.hover_key == "go" else 0.0
                w = paint.draw_text(p, x, y, q, look.LIST_PX, look.mix(look.DIM, look.TEXT, hv), glow=hv)
                if live:
                    self.regions.append((QRectF(x - 2, y - 2, w + 6, 20), "go", self._pasted))
                hv2 = 1.0 if self.hover_key == "change" else 0.0
                cw = paint.draw_text(p, x + w + 10, y + 2, "Change.", look.NOTE_PX,
                                     look.mix(look.FAINT, look.TEXT, hv2))
                if live:
                    self.regions.append((QRectF(x + w + 8, y, cw + 6, 18), "change",
                                         lambda: setattr(self, "choosing", not self.choosing)))
                y += 24
                if self.choosing:
                    for key, label in (("qbittorrent", "qBittorrent"), ("aria2", "aria2")):
                        on = key == prog
                        hk = "prog:" + key
                        hv3 = 1.0 if self.hover_key == hk else 0.0
                        paint.draw_text(p, x + 12, y, label, look.NOTE_PX + 1,
                                        look.mix(look.TEXT if on else look.FAINT, look.TEXT, hv3))
                        self._ring(p, x + width - 8, y + 8, on)
                        if live:
                            self.regions.append((QRectF(x + 4, y - 2, width, 20), hk,
                                                 lambda k=key: self._choose(k)))
                        y += 20
            self.dl_h.set(max(70.0, y - full.top() + 8))
            return
        if job is None:
            self.dl_h.set(84)
            return
        stage = getattr(job, "stage", "")
        if job.failed:
            state = "failed"
        elif stage in ("checking", "ready", "held"):
            state = stage
        elif job.percent >= 0:
            bits = [f"{job.percent}%"]
            if job.speed and not job.speed.startswith("0"):
                bits.append(job.speed.replace("iB", "B") + "/s")
            if job.eta:
                bits.append(job.eta + " left")
            state = "  ·  ".join(bits)
        else:
            state = "starting"
        paint.draw_text(p, x, y, state, look.NOTE_PX, look.BAD if state in ("failed", "held") else look.FAINT)
        y += 20
        # progress: the share done as a brighter stretch of a faint line (busy bar when unknown)
        if not job.finished or stage == "checking":
            # the real share done, from the torrent program (full while it is being checked)
            done = 100 if stage == "checking" else max(0, job.percent)
            p.fillRect(QRectF(x, y, width, 2), look.alpha(look.FAINT, 0.45))
            if done:
                p.fillRect(QRectF(x, y, width * done / 100, 2), QColor(0xe8, 0xea, 0xee, int(0.85 * 255)))
            y += 12
        if stage == "ready" and job.landed:
            key = "open"
            hv2 = 1.0 if self.hover_key == key else 0.0
            w = paint.draw_text(p, x, y, "open", look.NOTE_PX, look.mix(look.DIM, look.TEXT, hv2))
            if live:
                self.regions.append((QRectF(x - 2, y - 2, w + 6, 18), key,
                                     lambda: self.main.play_landed(job.landed)))
            y += 20
        lines, links = [], []
        if stage == "held":
            lines = job.reasons
            links = [("keep it anyway", lambda: self.main.keep_held(job)),
                     ("throw it away", lambda: self.main.discard_held(job))]
        elif job.failed:
            lines = [job.error]
            if getattr(job, "needs", ""):
                links = [(f"download {job.needs} for Bramble", lambda: self.main.get_tool(job.needs))]
        for line in lines:
            for chunk in _wrap(line, look.NOTE_PX, width):
                paint.draw_text(p, x, y, chunk, look.NOTE_PX, look.ERR_TEXT)
                y += 15
        if links:
            y += 4
            lx = x
            for i, (text, fn) in enumerate(links):
                key = f"dl-link:{i}"
                hv2 = 1.0 if self.hover_key == key else 0.0
                w = paint.draw_text(p, lx, y, text, look.NOTE_PX, look.mix(look.DIM, look.TEXT, hv2))
                if live:
                    self.regions.append((QRectF(lx - 2, y - 2, w + 6, 18), key, fn))
                lx += w + 14
            y += 18
        self.dl_h.set(max(84.0, y - full.top() + 10))

    def _ring(self, p, cx, cy, on: bool) -> None:
        """Hawthorn's ring: filled when chosen, a faint circle when not."""
        from PyQt6.QtGui import QPen
        p.save()
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(232, 234, 238, int(0.95 * 255)))
        else:
            pen = QPen(QColor(141, 148, 162, int(0.45 * 255)))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 3.4, 3.4)
        p.restore()

    def _busy(self, p, x, y) -> None:
        p.fillRect(QRectF(x, y, 90, 2), look.alpha(look.FAINT, 0.45))
        phase = (time.monotonic() % 2.2) / 1.1
        if phase > 1:
            phase = 2 - phase
        p.fillRect(QRectF(x + 68 * look.cosine(phase), y, 22, 2), QColor(0xe8, 0xea, 0xee, int(0.85 * 255)))

    # --- input -----------------------------------------------------------------------
    def _hit(self, pos: QPointF):
        for rect, key, fn in reversed(self.regions):
            if rect.contains(pos):
                return key, fn
        return None, None

    def mouseMoveEvent(self, ev) -> None:
        key, _ = self._hit(ev.position())
        if key != self.hover_key:
            self.hover_key = key
            for k, prop in self.row_hover.items():
                prop.set(1.0 if k == key else 0.0)
            self.results_card.close_hover.set(1.0 if key == "close-results" else 0.0)
            self.dl_card.close_hover.set(1.0 if key == "close-download" else 0.0)
        self.setCursor(Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, _e) -> None:
        self.hover_key = None
        for prop in self.row_hover.values():
            prop.set(0.0)
        self.results_card.close_hover.set(0.0)
        self.dl_card.close_hover.set(0.0)

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        key, fn = self._hit(ev.position())
        if fn:
            fn()

    def wheelEvent(self, ev) -> None:
        if self.results_rect().contains(ev.position()):
            most = max(0.0, getattr(self, "content_h", 0) - getattr(self, "view_h", 0) + 8)
            self.scroll = max(0.0, min(most, self.scroll - ev.angleDelta().y() / 120 * ROW_H))

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key.Key_Escape:
            self.main.escape_search()


def _wrap(text: str, px: float, width: float) -> list[str]:
    f = paint.font(px)
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if paint.width(trial, f) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _size(n: int) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""
