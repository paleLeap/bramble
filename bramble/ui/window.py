"""Bramble's window: paleleap.com's page, at Hawthorn's size.

    bramble                       x
          + movies
          + tv shows
          + video games
          + music
          +

Clicking a category: the others slide left and fade, it steps right and grows,
a line grows across and down from it (Hawthorn's corner lines) and a card
unfolds from the corner with that category's titles. Clicking the category
again, or the card's x, plays it all backwards.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QLineEdit, QWidget

from .. import downloads, fetch, kinds, launcher, library, paths, system, tools
from . import anim, look, paint
from .background import Background
from .panel import Panel


class _Bridge(QObject):
    done = pyqtSignal(object)


class Row:
    def __init__(self, cat: library.Category | None):
        self.cat = cat                         # None: the "+" that makes a new category
        self.x = anim.Prop(0.0, look.MOVE_MS)
        self.op = anim.Prop(1.0, look.FADE_MS)
        self.scale = anim.Prop(1.0, look.MOVE_MS)
        self.hover = anim.Prop(0.0, look.COLOR_MS, look.css_ease)
        self.mark = anim.Prop(0.0, look.MARK_MS, look.css_ease)
        self.open = anim.Prop(0.0, look.COLOR_MS, look.css_ease)
        self.turn = anim.Prop(0.0, look.MOVE_MS)              # "+" turning into "\u2212"

    @property
    def label(self) -> str:
        return self.cat.label if self.cat else ""

    def moving(self) -> bool:
        return any(p.moving for p in (self.x, self.op, self.scale, self.hover, self.mark, self.open,
                                      self.turn))


class CopyJob:
    """A file being copied into a category; drawn like a download."""

    def __init__(self, src: Path, title: str):
        import uuid
        self.id = uuid.uuid4().hex[:8]
        self.src = src
        self.title = title
        self.folder: Path | None = None
        self.finished = self.failed = False
        self.error = ""

    @property
    def state_text(self) -> str:
        return "failed" if self.failed else "done" if self.finished else "copying"


class BrambleWindow(QWidget):
    def __init__(self, settings):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.settings = settings
        self.setWindowTitle("bramble")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(look.WMIN, look.HMIN)
        self.resize(look.W0, look.H0)
        scr = self.screen().availableGeometry() if self.screen() else None
        if scr is not None:
            self.move(scr.center().x() - look.W0 // 2, scr.center().y() - look.H0 // 2)

        self.bg = Background()
        self.rows: list[Row] = []
        self.open_row: Row | None = None
        self.shown_row: Row | None = None      # the row the card belongs to (kept while closing)
        self.timeline = anim.Timeline(look.CARD_TEXT[1])
        self.panel: Panel | None = None
        self.returning = False                         # closing: the lines wait for the card
        self.brand_a = anim.Prop(look.TEXT_SOFT, look.BRAND_MS, look.css_ease)
        self.close_hover = anim.Prop(0.0, look.COLOR_MS, look.css_ease)
        self.hover_key: str | None = None
        self.regions: list[tuple[QRectF, str, object]] = []
        self.copies: list[CopyJob] = []

        self._bridge = _Bridge()
        self._bridge.done.connect(lambda t: t[0](t[1], t[2]))
        self.downloads = downloads.Downloads(settings, lambda job: self._bridge.done.emit(
            (lambda *_: self.refresh_panel(), None, None)))

        self.entry = QLineEdit(self)
        self.entry.hide()
        self.entry.setFrame(False)
        self.entry.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {look.TEXT.name()}; border: none;"
            f" border-bottom: 1px solid {look.FAINT.name()}; padding: 0px; }}")
        self.entry.setFont(paint.font(look.LIST_PX))
        self.entry.returnPressed.connect(self._entry_done)
        self.entry_for: str = ""                 # "category" or "add"

        self.set_categories(library.categories(settings))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self.rescan_timer = QTimer(self, interval=20000)
        self.rescan_timer.timeout.connect(self.refresh_panel)
        self.rescan_timer.start()
        QTimer.singleShot(500, self.downloads.resume_saved)

    # --- background work -----------------------------------------------------------
    def run(self, fn, done=None) -> None:
        import threading

        def go():
            try:
                res, err = fn(), None
            except Exception as e:          # handed back to the window, never lost
                res, err = None, e
            if done:
                self._bridge.done.emit((done, res, err))
        threading.Thread(target=go, daemon=True).start()

    # --- categories ------------------------------------------------------------------
    def set_categories(self, cats: list[library.Category]) -> None:
        old = {r.cat.name: r for r in self.rows if r.cat}
        rows = [old.get(c.name) or Row(c) for c in cats]
        for r, c in zip(rows, cats):
            r.cat = c
        plus = next((r for r in self.rows if r.cat is None), None) or Row(None)
        self.rows = rows + [plus]
        self._settle()

    def _settle(self) -> None:
        """The site's rules: chosen one steps right and grows, the rest slide left and fade."""
        if self.returning:
            return                     # nothing moves back until the card has folded away
        for r in self.rows:
            if self.open_row is None:
                r.x.set(0.0)
                r.op.set(1.0)
                r.scale.set(look.HOVER_SCALE if (r.hover.target > 0 and r.cat) else 1.0)
                r.open.set(0.0)
                r.turn.set(0.0)
            elif r is self.open_row:
                r.x.set(look.STEP)
                r.op.set(1.0)
                r.scale.set(look.OPEN_SCALE)
                r.open.set(1.0)
                r.turn.set(1.0)
            else:
                r.x.set(-look.SLIDE)
                r.op.set(0.0)
                r.scale.set(1.0)
                r.open.set(0.0)
                r.turn.set(0.0)
        opened = self.open_row is not None
        self.brand_a.set(look.TEXT_GHOST if opened else look.TEXT_SOFT)

    def toggle(self, row: Row) -> None:
        if row.cat is None:
            self.start_entry("category")
            return
        if self.open_row is row:
            self.close_category()
            return
        self.hide_entry()
        if self.returning and row is self.shown_row and self.panel:
            # clicked again while it was closing: open it back up from where it is
            self.returning = False
            self.open_row = row
            self.timeline.open()
            self._settle()
            return
        self.returning = False
        self.open_row = row
        self.shown_row = row
        self.panel = Panel(self, row.cat)
        self.timeline.open()
        self._settle()
        self.refresh_panel()

    def close_category(self) -> None:
        if self.open_row is None:
            return
        self.hide_entry()
        if self.panel:
            self.panel.cancel_adding()
        self.open_row = None
        self.timeline.close()
        self.returning = True          # _tick lets the lines back once the card is gone

    def refresh_panel(self) -> None:
        if not self.panel:
            return
        panel = self.panel
        cat = panel.category

        def work():
            fresh = {c.name: c for c in library.categories(self.settings)}
            c = fresh.get(cat.name, cat)
            return c, library.scan_category(c)

        def done(res, err):
            if err or res is None or panel is not self.panel:
                return
            c, items = res
            panel.category = c
            jobs = self.downloads.for_folder([c.home] + c.folders)
            jobs += [j for j in self.copies if j.folder in ([c.home] + c.folders)
                     and not (j.finished and not j.failed)]
            panel.set_items(items, jobs)
            panel.preload()
        self.run(work, done)

    # --- the text box (a new category, or a link to add) ------------------------------
    def start_entry(self, what: str) -> None:
        self.entry_for = what
        self.entry.clear()
        if what == "category":
            i = len(self.rows) - 1
            y = look.MENU_TOP + i * look.ROW
            self.entry.setGeometry(int(self.x0 + look.MARKER_W), int(y + 2),
                                   int(min(170, self.width() - self.x0 - look.MARKER_W - 20)), 19)
            self.entry.setFont(paint.font(look.MENU_PX))
        self.entry.show()
        self.entry.setFocus()

    def show_entry(self) -> None:
        self.entry_for = "add"
        self.entry.clear()
        self.entry.setFont(paint.font(look.LIST_PX))
        self.entry.show()
        self.entry.setFocus()

    def place_entry(self, r: QRectF) -> None:
        if self.entry_for == "add" and self.entry.isVisible():
            self.entry.setGeometry(int(r.left()), int(r.top() + 2), int(r.width()), 19)

    def hide_entry(self) -> None:
        self.entry.hide()
        self.entry_for = ""
        self.setFocus()

    def _entry_done(self) -> None:
        text = self.entry.text().strip()
        what = self.entry_for
        self.hide_entry()
        if not text:
            if self.panel:
                self.panel.mode = "list"
            return
        if what == "category":
            name = "".join(ch for ch in text if ch not in '/\\:*?"<>|').strip()
            if name:
                home = library.categories(self.settings)[0].home.parent
                try:
                    (home / name).mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
                self.set_categories(library.categories(self.settings))
            return
        if what == "add" and self.panel:
            self.panel.mode = "list"
            cat = self.panel.category
            p = Path(text.strip('"').strip("'"))
            if p.exists() and not text.lower().endswith(".torrent"):
                self.add_file(cat, p)
            elif downloads.looks_like_link(text):
                cat.home.mkdir(parents=True, exist_ok=True)
                self.downloads.start(text, cat.home)
                self.refresh_panel()

    # --- adding files ------------------------------------------------------------------
    def add_file(self, cat: library.Category, src: Path) -> None:
        if src.suffix.lower() == ".torrent":
            cat.home.mkdir(parents=True, exist_ok=True)
            self.downloads.start(str(src), cat.home)
            self.refresh_panel()
            return
        dest = cat.home
        kind = kinds.classify(src, cat.name if cat.kind != "custom" else None)
        if cat.kind in ("tv", "games"):
            for part in kinds.suggested_subfolder(Path(src.name), kind):
                dest = dest / part
        job = CopyJob(src, kinds.nice_title(src)[0] if src.is_file() else src.name)
        job.folder = cat.home
        self.copies.append(job)
        self.refresh_panel()

        def work():
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / src.name
            if target.exists():
                raise FileExistsError(f"{src.name} is already there.")
            if src.is_dir():
                shutil.copytree(src, target)
            else:
                tmp = target.with_name(target.name + ".bramble-part")
                shutil.copyfile(src, tmp)
                shutil.copystat(src, tmp)
                tmp.replace(target)
            return target

        def done(res, err):
            job.finished = True
            if err:
                job.failed, job.error = True, str(err)
            self.refresh_panel()
        self.run(work, done)

    # --- opening -----------------------------------------------------------------
    def play(self, item, panel: Panel) -> None:
        info = panel.infos.get(item.key)
        pr = info.pr if info else None
        if info:
            info.busy = True
        settings = self.settings

        def work():
            ways = launcher.ways_for(item, settings, pr)
            return launcher.try_ways(item, ways)

        def done(outcome, err):
            if err:
                from ..launcher import Attempt, Outcome
                outcome = Outcome(False, attempts=[Attempt("Bramble", False, str(err))])
            panel.opened(item, outcome)
            if outcome.ok:
                tool = outcome.used.split(" (")[0].lower()
                if tool in ("vlc", "mpv"):
                    lg = dict(settings["last_good"])
                    lg[item.kind] = tool
                    settings["last_good"] = lg
        self.run(work, done)

    def fix(self, f, item, panel: Panel) -> None:
        info = panel.infos.get(item.key) if item else None
        if info:
            info.busy = True

        def work():
            if f.run:
                return f.run()
            if f.install:
                t = tools.TOOLS[f.install]
                cmd = system.install_command(t.install_hint_linux, t.install_hint_windows)
                if not cmd:
                    return False, f"{t.name} cannot be installed here automatically."
                import subprocess
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                if r.returncode == 0:
                    return True, ""
                if paths.IS_LINUX and cmd[0] == "pkexec":
                    return False, (f"{t.name} was not installed. In a terminal: "
                                   f"sudo {' '.join(cmd[1:])}")
                return False, (r.stderr or r.stdout).strip()[-300:]
            if f.download:
                rel, errors = fetch.latest(f.download)
                if rel is None:
                    return False, "No download site answered. " + (errors[0] if errors else "")
                dest = self._tools_destination()
                fetch.install(rel, dest)
                return True, ""
            return False, ""

        def done(res, err):
            ok = (not err) and res and res[0]
            if item is None:
                # a download's fix: once the missing program is here, try the downloads again
                if ok:
                    self.downloads.retry_failed()
                self.refresh_panel()
                return
            if not info:
                return
            info.busy = False
            ok, msg = (False, str(err)) if err else res
            if ok:
                panel.infos.pop(item.key, None)
                panel._load_info(item)
            else:
                info.error = [msg] if msg else []
        self.run(work, done)

    def _tools_destination(self) -> Path:
        for drive in paths.find_drives():
            dest = paths.drive_tools(drive)
            try:
                dest.mkdir(parents=True, exist_ok=True)
                t = dest / ".bramble-write-test"
                t.write_text("x")
                t.unlink()
                return dest
            except OSError:
                continue
        return paths.local_tools()

    # --- geometry ----------------------------------------------------------------
    @property
    def x0(self) -> float:
        """The menu's "+" sits under the third letter of the name, as on the site."""
        f = paint.font(look.BRAND_PX, look.BRAND_WEIGHT, look.BRAND_TRACK)
        return look.BRAND_POS[0] + paint.width("br", f)

    def _row_y(self, i: int) -> float:
        return look.MENU_TOP + i * look.ROW

    def _card_geometry(self) -> QRectF | None:
        """The card: centred across the window under the chosen line, a fixed height
        (it never resizes while open; only the hovered title grows inside it)."""
        row = self.shown_row
        if row is None or row not in self.rows:
            return None
        top = self._row_y(self.rows.index(row)) + look.ROW + 12
        w, h = self.width(), self.height()
        height = max(look.ROW * 2 + 2 * look.CARD_PAD, h - top - look.CARD_BOTTOM)
        return QRectF(look.CARD_MARGIN, top, w - 2 * look.CARD_MARGIN, height)

    # --- frame ----------------------------------------------------------------------
    def _tick(self) -> None:
        self.bg.tick()
        if self.returning and self.timeline.position() <= look.CARD_OPEN[0]:
            self.returning = False     # the card has folded away: now the lines come back
            self._settle()
        if self.panel and self.timeline.shut and self.open_row is None and not self.returning:
            self.panel = None
            self.shown_row = None
        self.update()
        busy = (self.timeline.moving or any(r.moving() for r in self.rows) or self.brand_a.moving or self.close_hover.moving or self.returning
                or (self.panel and self.panel.moving()))
        self.timer.setInterval(16 if busy else 33)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        full = QRectF(0, 0, w, h)
        p.setClipPath(paint.rounded(full))
        self.bg.paint(p, full)
        self.regions = []
        self._paint_brand(p)
        self._paint_rows(p)
        self._paint_card(p)
        self._paint_close(p, w)
        p.end()

    def _brand_origin(self) -> tuple[float, float]:
        """Where "bramble" is drawn so the space above its tall letters equals the space
        to the left of it. It stays there when a category opens; only its colour fades."""
        from PyQt6.QtGui import QFontMetricsF
        f = paint.font(look.BRAND_PX, look.BRAND_WEIGHT, look.BRAND_TRACK)
        m = QFontMetricsF(f)
        b = m.tightBoundingRect("b")
        x = look.BRAND_POS[0]
        margin = x + b.left()
        return x, margin - m.ascent() - b.top()

    def _paint_brand(self, p: QPainter) -> None:
        x, y = self._brand_origin()
        paint.draw_text(p, x, y, "bramble", look.BRAND_PX, look.alpha(look.TEXT, self.brand_a.value),
                        look.BRAND_WEIGHT, look.BRAND_TRACK)

    def _paint_rows(self, p: QPainter) -> None:
        f = paint.font(look.MENU_PX, look.MENU_WEIGHT, look.MENU_TRACK)
        plus_w = paint.width("+", f)
        for i, r in enumerate(self.rows):
            op = r.op.value
            if op <= 0.002:
                continue
            y = self._row_y(i)
            x = self.x0 + r.x.value
            s = r.scale.value
            hv, on = r.hover.value, r.open.value
            cy = y + look.ROW / 2
            if r.cat is None:
                # the "+" for a new category: invisible until hovered, centred under the
                # first letter of the name above it
                above = self.rows[i - 1].label if i else ""
                cx = self.x0 + look.MARKER_W + paint.first_letter_centre(
                    above, look.MENU_PX, look.MENU_WEIGHT, look.MENU_TRACK) + r.x.value
                if self.entry_for != "category":
                    if hv > 0.01:
                        p.save()
                        p.setOpacity(op)
                        paint.draw_marker(p, cx, cy, look.MENU_PX, 0.0, look.alpha(look.DIM, hv))
                        p.restore()
                    if op > 0.5:
                        self.regions.append((QRectF(cx - 11, y, 22, look.ROW), f"row:{i}",
                                             lambda r=r: self.toggle(r)))
                continue
            p.save()
            p.setOpacity(op)
            p.translate(x, cy)
            p.scale(s, s)
            p.translate(-x, -cy)
            ty = cy - paint.text_height(f) / 2
            mcol = look.mix(look.FAINT, look.DIM, max(r.mark.value, on))
            paint.draw_marker(p, x + plus_w / 2, cy, look.MENU_PX, r.turn.value, mcol)
            col = look.mix(look.FAINT, look.TEXT, max(hv, on))
            tw = paint.draw_text(p, x + look.MARKER_W, ty, r.label, look.MENU_PX, col,
                                 look.MENU_WEIGHT, look.MENU_TRACK, glow=hv)
            p.restore()
            if op > 0.5 and not self.returning:
                hit = QRectF(x - 4, y, (look.MARKER_W + tw) * s + 10, look.ROW)
                self.regions.append((hit, f"row:{i}", lambda r=r: self.toggle(r)))

    def _paint_card(self, p: QPainter) -> None:
        card = self._card_geometry()
        if card is None or self.timeline.shut:
            return
        unfold = self.timeline.part(look.CARD_OPEN)
        text = self.timeline.part(look.CARD_TEXT)
        if unfold <= 0.002:
            return
        # it opens downward out of the space under the chosen line
        r = QRectF(card.left(), card.top(), card.width(), card.height() * unfold)
        p.save()
        p.setOpacity(unfold)
        # depth: a soft shadow under it, so it reads as a second window above the first
        for k in range(look.SHADOW, 0, -1):
            a = 0.05 * (1 - k / (look.SHADOW + 1))
            p.fillPath(paint.rounded(r.adjusted(-k, -k + 2, k, k + 2), look.RADIUS + k),
                       QColor(0, 0, 0, int(255 * a)))
        p.setClipPath(paint.rounded(r), Qt.ClipOperation.IntersectClip)
        self.bg.paint(p, r, look.GLASS_SCRIM, blur=True)
        p.setOpacity(1.0)
        if self.panel:
            self.panel.paint(p, card, text, look.SLIDE * (1 - text))
            if text > 0.5:
                self.regions.extend(self.panel.regions)
        p.restore()

    def _paint_close(self, p: QPainter, w: float) -> None:
        cell = QRectF(w - look.CLOSE_CELL, 0, look.CLOSE_CELL, look.CLOSE_CELL)
        # invisible until hovered, as Hawthorn's
        col = look.alpha(look.TEXT, self.close_hover.value)
        f = paint.font(13)
        tw = paint.width("×", f)
        paint.draw_text(p, cell.center().x() - tw / 2, cell.center().y() - paint.text_height(f) / 2,
                        "×", 13, col)
        self.regions.append((cell, "close", self.close))

    # --- input ------------------------------------------------------------------------
    def _hit(self, pos: QPointF):
        for rect, key, fn in reversed(self.regions):
            if rect.contains(pos):
                return key, fn
        return None, None

    def _edges(self, pos: QPointF) -> Qt.Edge:
        e = Qt.Edge(0)
        if pos.x() >= self.width() - look.EDGE:
            e |= Qt.Edge.RightEdge
        if pos.y() >= self.height() - look.EDGE:
            e |= Qt.Edge.BottomEdge
        return e

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        key, _ = self._hit(pos)
        if key != self.hover_key:
            self.hover_key = key
            for i, r in enumerate(self.rows):
                on = key == f"row:{i}"
                r.hover.set(1.0 if on else 0.0)
                r.mark.set(1.0 if on else 0.0)
            self._settle()
            self.close_hover.set(1.0 if key == "close" else 0.0)
            if self.panel:
                self.panel.hover(key)
        edges = self._edges(pos)
        if key:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif edges == (Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges == Qt.Edge.RightEdge:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges == Qt.Edge.BottomEdge:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def leaveEvent(self, _e) -> None:
        self.mouseMoveEvent(type("E", (), {"position": lambda s: QPointF(-100, -100)})())

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        pos = ev.position()
        key, fn = self._hit(pos)
        if fn:
            fn()
            return
        if self.entry.isVisible() and self.entry_for == "category":
            self.hide_entry()
        card = self._card_geometry()
        if self.panel and self.panel.mode != "list" and (card is None or not card.contains(pos)):
            self.panel.cancel_adding()
            return
        edges = self._edges(pos)
        handle = self.windowHandle()
        if edges and handle:
            handle.startSystemResize(edges)
        elif handle:
            handle.startSystemMove()

    def wheelEvent(self, ev) -> None:
        card = self._card_geometry()
        if self.panel and card and card.contains(ev.position()):
            self.panel.wheel(ev.angleDelta().y() / 120 * look.ROW * 2)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key.Key_Escape:
            if self.entry.isVisible() and self.entry_for == "category":
                self.hide_entry()
            elif self.panel and self.open_row and self.panel.back():
                pass
            elif self.open_row:
                self.close_category()
            else:
                self.close()

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls() and self.open_row is not None:
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        if not self.panel:
            return
        for url in ev.mimeData().urls():
            if url.isLocalFile():
                self.add_file(self.panel.category, Path(url.toLocalFile()))
            else:
                self.downloads.start(url.toString(), self.panel.category.home)
        self.refresh_panel()

    def closeEvent(self, ev) -> None:
        self.downloads.stop_all()
        super().closeEvent(ev)
