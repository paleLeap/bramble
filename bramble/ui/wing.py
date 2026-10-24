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

Confirm. asks where to save it, among the person's own categories (the one that fits
marked). Once it is downloading the results window folds away and the download window
rises into its place, on the line from the search box.

Out of the way when not in use: something new (results, the paste box, a finished
download) shows them fully for a moment, then they fade back to a faint REST until
the pointer is over them or the paste box is being typed in.

All of it is drawn on one see-through window beside Bramble that follows it;
it only takes clicks where something is drawn.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QRegion
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLineEdit, QWidget

from .. import downloads, kinds, library, sources
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
REST = 0.22              # how faint the side windows rest when the pointer is elsewhere
WAKE_S = 3.0             # how long something new shows fully before they fade back


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
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)     # Enter and Escape once the box is gone
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
        self.finding = False             # asking the result's site for its magnet link
        self.focus_paste = True          # take the keyboard when the box shows (not when the browser has it)
        self.placing = False             # Confirm. pressed: asking which category to save into
        self.solo = anim.Prop(0.0, look.MOVE_MS)   # 1: downloading, in the results window's place
        self.name_box = QLineEdit(self)  # a new category's name, typed while placing
        self.name_box.hide()
        self.name_box.setFrame(False)
        self.name_box.setPlaceholderText("New category.")
        self.name_box.setStyleSheet(self.paste.styleSheet())
        self.name_box.setPalette(pal)
        self.name_box.setFont(paint.font(look.NOTE_PX + 1))
        self.name_box.returnPressed.connect(self._named)
        self.name_box.setGraphicsEffect(QGraphicsOpacityEffect(self.name_box))
        self.handed = False              # the link came from outside (the browser), not a search
        self.over = False                # the pointer is on a side window
        self.woke = 0.0                  # when something new last appeared (time.monotonic)
        self.seen_state = ""             # the download's last state worth waking for
        self.presence = anim.Prop(1.0, look.FADE_MS, look.css_ease)
        self.paste_fade = QGraphicsOpacityEffect(self.paste)
        self.paste.setGraphicsEffect(self.paste_fade)

    def wake(self) -> None:
        """Something new to see: show fully, and fade back after WAKE_S if nobody looks."""
        self.woke = time.monotonic()
        self.presence.set(1.0)

    def _awake(self) -> bool:
        return (self.over or self.paste.hasFocus() or self.name_box.hasFocus() or self.searching
                or self.choosing or self.placing or time.monotonic() - self.woke < WAKE_S)

    # --- where it sits ------------------------------------------------------------
    def follow(self, at=None) -> None:
        """Sit against Bramble's right edge; `at` is where Bramble is going (mid-drag, before
        its own geometry has caught up)."""
        g = self.main.geometry()
        x, y = (at.x(), at.y()) if at is not None else (g.x(), g.y())
        self.setGeometry(x + g.width(), y, WING_W, g.height() + WING_EXTRA)

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
        """Under the results window; while downloading, risen into its place (bottom-aligned
        with it, so the line from the search box meets it where it met the results)."""
        r = self.results_rect()
        h = self.dl_h.value
        k = self.solo.value
        x = r.left() + DL_SHIFT + (r.left() - (r.left() + DL_SHIFT)) * k
        y = r.bottom() + 22 + ((r.bottom() - h) - (r.bottom() + 22)) * k
        y = min(y, self.height() - h - 10)        # grown (the categories): up, never cut off
        return QRectF(x, y, DL_W, h)

    def search_y(self) -> float:
        return self.main.height() - 24          # the middle of Bramble's search box

    # --- opening and closing -------------------------------------------------------
    def open_results(self, query: str) -> None:
        self.query = query
        self.results, self.note, self.searching = [], "", True
        self.handed = False
        self.scroll = 0.0
        self.close_download()
        self.follow()
        self.show()
        self.raise_()
        self.wake()
        self.results_card.tl.open()

    def set_results(self, results: list, note: str) -> None:
        self.results, self.note, self.searching = results, note, False
        self.wake()

    def close_results(self) -> None:
        self.close_download()
        self.results_card.tl.close()

    def open_download(self, result, row_y: float, job) -> None:
        self.chosen, self.chosen_row_y, self.job = result, row_y, job
        self.pasting = self.placing = False
        self.paste.hide()
        self.name_box.hide()
        if not self.dl_card.shown:
            self.solo.jump(0.0)
        self.wake()
        self.dl_card.tl.open()

    def open_paste(self, result, row_y: float, prefill: str = "", focus: bool = True) -> None:
        """The download window, asking for the link the person copies from the site's page.
        focus=False when that page has just opened in the browser: the browser stays in front
        (the box still fills itself from the clipboard, and then comes forward)."""
        self.chosen, self.chosen_row_y, self.job = result, row_y, None
        self.focus_paste = focus
        self.pasting = True
        self.choosing = self.placing = False
        self.finding = False
        self.name_box.hide()
        if not self.dl_card.shown:
            self.solo.jump(0.0)
        self.paste.setText(prefill)
        self.wake()
        self.dl_card.tl.open()

    def clipboard_changed(self) -> None:
        """A magnet link copied while the box is waiting goes straight into it (not started)."""
        if not self.pasting or self.paste.text().strip():
            return
        from PyQt6.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if text.startswith("magnet:?") or text.lower().split("?")[0].endswith(".torrent"):
            self.paste.setText(text)
            self.wake()
            self.main.raise_()
            self.raise_()

    def origin(self) -> str:
        """Where the link came from, as the person would say it."""
        r = self.chosen
        if r is None:
            return ""
        return r.title if getattr(r, "site", False) else r.source

    def _deny(self) -> None:
        """Not that one. From a site's page: wait for another. Otherwise: put it away."""
        self.choosing = False
        self.placing = False
        self.name_box.hide()
        if getattr(self.chosen, "site", False):
            self.paste.clear()
        elif self.handed:
            self.close_results()
        else:
            self.close_download()

    def _link_ok(self) -> bool:
        link = self.paste.text().strip()
        return bool(link) and (link.startswith("magnet:?") or downloads.looks_like_link(link))

    def _pasted(self) -> None:
        """Confirm. (or Enter): ask where it goes. Enter while asking: the marked category."""
        if not self._link_ok():
            return
        if self.placing:
            fit = self._fitting()
            self._start(fit.home if fit else None)
            return
        if not library.categories(self.main.settings):
            self._start(None)                # no categories yet: filed by kind, as before
            return
        self.placing = True
        self.choosing = False
        self.wake()

    def _open_page(self) -> None:
        r = self.chosen
        self.main._open_in_browser(r.page, r.source)

    def _start(self, into: Path | None) -> None:
        r = self.chosen
        if getattr(r, "borrow", False):
            # a book the library lends: keep its page in the category, nothing to download
            self.main.save_link(r.title, r.page, into)
            self.placing = False
            self.name_box.hide()
            self.close_download()
            return
        link = self.paste.text().strip()
        self.pasting = self.placing = self.choosing = False
        self.paste.hide()
        self.name_box.hide()
        r = self.chosen
        site = bool(r and getattr(r, "site", False))
        self.job = self.main.start_link(link, title=r.title if (r and not site) else "",
                                        source_link=r.link if (r and not site) else "",
                                        program=self.main.settings["torrent_program"], into=into)
        # the results have done their part: fold them away, the download rises into their place
        self.results_card.tl.close()
        self.solo.set(1.0)
        self.wake()

    def _named(self) -> None:
        """A new category typed while placing: make its folder and save there."""
        name = self.name_box.text().strip().strip("/\\")
        if not name or name.startswith("."):
            return
        home = self.main.new_category_folder(name)
        if home is not None:
            self._start(home)

    def _shown_title(self) -> str:
        r = self.chosen
        if r is not None and getattr(r, "site", False) and self._link_ok():
            return downloads.title_of(self.paste.text())
        return r.title if r is not None else ""

    def _fitting(self):
        """The person's category this most likely belongs in, by its name and source."""
        r, title = self.chosen, self._shown_title()
        group = ""
        if getattr(r, "kind_hint", "") == "book" or re.search(r"(?i)\b(pdf|epub|mobi|azw3)\b", title):
            group = "books"
        elif kinds.episode_info(Path(kinds._tidy(title) + ".x")) or re.search(
                r"(?i)\b(s\d\d|season \d+|complete series)\b", kinds._tidy(title)):
            group = "tv"
        elif getattr(r, "quality", "") or re.search(
                r"(?i)\b(2160p|1080p|720p|480p|bluray|web-?dl|webrip|x26[45]|hevc)\b", title):
            group = "movies"
        elif re.search(r"(?i)\b(flac|mp3|album|discography)\b", title):
            group = "music"
        return next((c for c in library.categories(self.main.settings) if c.kind == group), None)

    def _choose(self, program: str) -> None:
        self.main.settings["torrent_program"] = program
        self.choosing = False

    def close_download(self) -> None:
        self.pasting = self.placing = False
        self.finding = False
        self.name_box.hide()
        self.paste.hide()
        self.dl_card.tl.close()

    def moving(self) -> bool:
        return (self.results_card.tl.moving or self.dl_card.tl.moving or self.searching
                or self.dl_h.moving or (self.job is not None and not self.job.finished)
                or any(p.moving for p in self.row_hover.values())
                or self.results_card.close_hover.moving or self.dl_card.close_hover.moving
                or self.presence.moving or time.monotonic() - self.woke < WAKE_S + 0.1
                or self.solo.moving)

    def tick(self) -> None:
        if not self.results_card.shown and not self.dl_card.shown:
            if self.isVisible():
                self.hide()
            return
        job = self.job
        state = job.state_text if job is not None and (job.finished or job.waiting) else ""
        if state != self.seen_state:
            self.seen_state = state
            if state:
                self.wake()              # ready, held, failed, or nobody sharing it
        target = 1.0 if self._awake() else REST
        if self.presence.target != target:
            self.presence.set(target)
        self.update()

    # --- drawing -------------------------------------------------------------------
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.regions = []
        mask = QRegion()
        fade = self.presence.value
        if fade >= 0.999:
            mask = mask.united(self._paint_results(p))
            mask = mask.united(self._paint_download(p))
        else:
            # the cards set their own opacities, so draw them whole and fade the picture
            dpr = self.devicePixelRatioF()
            img = QImage(int(self.width() * dpr), int(self.height() * dpr),
                         QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(Qt.GlobalColor.transparent)
            q = QPainter(img)
            q.setRenderHints(p.renderHints())
            mask = mask.united(self._paint_results(q))
            mask = mask.united(self._paint_download(q))
            q.end()
            p.setOpacity(fade)
            p.drawImage(0, 0, img)
        self.paste_fade.setOpacity(fade)
        self.name_box.graphicsEffect().setOpacity(fade)
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
        elif not self.results or self.note:
            # nothing found, or something to say about what was found ("No free copy ...")
            for line in _wrap(self.note or "Nothing found.", look.NOTE_PX, width):
                paint.draw_text(p, x, y, line, look.NOTE_PX, look.FAINT)
                y += 16
            if self.results:
                y += 8
        for r in self.results:
            key = "res:" + r.link
            hp = self.row_hover.setdefault(key, anim.Prop(0.0, look.COLOR_MS, look.css_ease))
            h = hp.value
            chosen = r is self.chosen and self.dl_card.tl.opening
            col = look.TEXT if chosen else look.mix(look.DIM, look.TEXT, h)
            title = paint.elide(r.title.replace("_", " "), look.LIST_PX, width)
            paint.draw_text(p, x, y + 2, title, look.LIST_PX, col, glow=h)
            facts = ("search page" if getattr(r, "site", False) else
                     "  ·  ".join(b for b in (r.quality, _size(r.size),
                                              f"{r.seeders} seeders" if r.seeders >= 0 else "",
                                              r.source) if b))
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
        k = self.solo.value
        bx = res.right() + 28
        corner = QPointF(bx, full.top())
        ry = max(res.top() + 10, min(res.bottom() - 10, self.chosen_row_y))
        # the line from the results row, gone as the results fold away
        keep = max(0.0, 1.0 - 2 * k)
        self._lines(p, [QPointF(res.right() + 4, ry), QPointF(bx, ry), QPointF(bx, full.top() - 6)],
                    card.part(0) * keep, card.part(1) * keep)
        region = QRegion(QRect(int(res.right()), int(ry) - 2, int(bx - res.right()) + 3, 5)).united(
            QRegion(QRect(int(bx) - 2, int(ry), 5, int(full.top() - ry) + 3))) if keep else QRegion()
        if k > 0.001:
            # risen into the results window's place: on the line from the search box, as it was
            sy, cx = self.search_y(), res.left() + 16
            self._lines(p, [QPointF(LINE_START, sy), QPointF(cx, sy), QPointF(cx, res.bottom() + 6)],
                        card.part(0), card.part(1))
            region = region.united(QRegion(QRect(0, int(sy) - 2, int(cx) + 3, 5))).united(
                QRegion(QRect(int(cx) - 2, int(res.bottom()), 5, int(sy - res.bottom()) + 3)))
            if k > 0.5:
                corner = QPointF(cx, full.bottom())      # it folds back into the line's end
        c = card.part(2)
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

    def _placing_rows(self, p: QPainter, x: float, y: float, width: float, live: bool) -> float:
        """Where to save it: the person's categories, the fitting one marked (Enter takes it),
        and a new one by name."""
        paint.draw_text(p, x, y, "Save to", look.NOTE_PX, look.FAINT)
        y += 22
        fit = self._fitting()
        for cat in library.categories(self.main.settings):
            hk = "into:" + cat.name
            hv = 1.0 if self.hover_key == hk else 0.0
            on = fit is not None and cat.name == fit.name
            paint.draw_text(p, x + 12, y, cat.label, look.LIST_PX,
                            look.mix(look.TEXT if on else look.DIM, look.TEXT, hv), glow=hv)
            self._ring(p, x + width - 8, y + 9, on)
            if live:
                self.regions.append((QRectF(x + 4, y - 2, width, 22), hk,
                                     lambda home=cat.home: self._start(home)))
            y += 24
        if self.name_box.isVisible():
            if live:
                self.name_box.setGeometry(int(x + 12), int(y), int(width - 12), 20)
            y += 28
        else:
            hv = 1.0 if self.hover_key == "into+" else 0.0
            paint.draw_text(p, x + 12, y, "+ new category", look.NOTE_PX + 1,
                            look.mix(look.FAINT, look.TEXT, hv))
            if live:
                self.regions.append((QRectF(x + 4, y - 2, width, 20), "into+", self._new_category))
            y += 24
        hv = 1.0 if self.hover_key == "back" else 0.0
        w = paint.draw_text(p, x, y + 2, "Back.", look.NOTE_PX, look.mix(look.FAINT, look.TEXT, hv))
        if live:
            self.regions.append((QRectF(x - 2, y, w + 6, 18), "back", self._unplace))
        return y + 22

    def _new_category(self) -> None:
        self.name_box.clear()
        self.name_box.show()
        self.activateWindow()
        self.name_box.setFocus()

    def _unplace(self) -> None:
        self.placing = False
        self.name_box.hide()
        self.setFocus()

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
        offered = self.pasting and not self.finding and self._link_ok()
        title = kinds._tidy(self.chosen.title)
        if getattr(self.chosen, "site", False):
            # what was searched, until the link brings its own name
            if self.job is not None:
                title = self.job.title
            elif offered:
                title = kinds._tidy(downloads.title_of(self.paste.text()))
            else:
                title = self.query
        lines = _wrap(title, look.LIST_PX, width)[:3] if offered else [paint.elide(title, look.LIST_PX, width)]
        for line in lines:
            paint.draw_text(p, x, y, line, look.LIST_PX, look.TEXT)
            y += 20
        y += 2
        if self.pasting and self.finding:
            if self.paste.isVisible():
                self.paste.hide()
            paint.draw_text(p, x, y, f"getting the link from {self.origin()}…", look.NOTE_PX, look.FAINT)
            self.dl_h.set(max(70.0, y + 28 - full.top()))
            return
        if self.pasting and not offered:
            # the box for the link from the site's page (or the browser, or the clipboard)
            if live:
                self.paste.setGeometry(int(x), int(y), int(width), 20)
                if not self.paste.isVisible():
                    self.paste.show()
                    if self.focus_paste:
                        self.activateWindow()
                        self.paste.setFocus()
            elif self.paste.isVisible():
                self.paste.hide()
            y += 30
            self.dl_h.set(max(70.0, y - full.top() + 8))
            return
        if offered:
            # the link is here: its name, where it came from, and Confirm. or Deny.
            if self.paste.isVisible():
                self.paste.hide()
                self.setFocus()                  # Enter confirms, Escape closes
            names = {"qbittorrent": "qBittorrent", "aria2": "aria2"}
            prog = self.main.settings["torrent_program"]
            torrent = downloads.is_torrent(self.paste.text())
            lent = getattr(self.chosen, "borrow", False)
            kind = getattr(self.chosen, "quality", "") or "file"
            facts = f"from {self.origin()}  ·  " + (
                "borrow free, with an account" if lent else
                names.get(prog, prog) if torrent else f"{kind} download")
            paint.draw_text(p, x, y, paint.elide(facts, look.NOTE_PX, width), look.NOTE_PX, look.FAINT)
            y += 24
            if self.placing:
                y = self._placing_rows(p, x, y, width, live)
                self.dl_h.set(max(70.0, y - full.top() + 8))
                return
            cx = x
            buttons = ((("open", "Open.", self._open_page), ("confirm", "Save link.", self._pasted))
                       if lent else (("confirm", "Confirm.", self._pasted),))
            for key, label, fn in buttons + (("deny", "Deny.", self._deny),):
                hv = 1.0 if self.hover_key == key else 0.0
                w = paint.draw_text(p, cx, y, label, look.LIST_PX, look.mix(look.DIM, look.TEXT, hv), glow=hv)
                if live:
                    self.regions.append((QRectF(cx - 2, y - 2, w + 6, 20), key, fn))
                cx += w + 16
            if torrent:                          # a plain file needs no torrent program
                hv2 = 1.0 if self.hover_key == "change" else 0.0
                cw = paint.width("Change.", paint.font(look.NOTE_PX))
                paint.draw_text(p, x + width - cw, y + 2, "Change.", look.NOTE_PX,
                                look.mix(look.FAINT, look.TEXT, hv2))
                if live:
                    self.regions.append((QRectF(x + width - cw - 2, y, cw + 6, 18), "change",
                                         lambda: setattr(self, "choosing", not self.choosing)))
            y += 24
            if self.choosing and torrent:
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

    def enterEvent(self, _e) -> None:
        self.over = True
        self.presence.set(1.0)

    def leaveEvent(self, _e) -> None:
        self.over = False
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
        elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.pasting and self._link_ok():
            self._pasted()


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
