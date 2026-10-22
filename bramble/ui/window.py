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

from .. import downloads, fetch, kinds, launcher, library, notify, paths, sources, system, tools
from . import anim, look, paint
from .background import Background
from .panel import Panel
from .wing import WING_EXTRA, WING_W, Wing


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
        self.brand_k = anim.Prop(0.0, look.BRAND_MS)  # the name drawing back toward its corner
        self.brand_a = anim.Prop(look.TEXT_SOFT, look.BRAND_MS, look.css_ease)
        self.close_hover = anim.Prop(0.0, look.COLOR_MS, look.css_ease)
        self.hover_key: str | None = None
        self.regions: list[tuple[QRectF, str, object]] = []
        self.copies: list[CopyJob] = []

        self._bridge = _Bridge()
        self._bridge.done.connect(lambda t: t[0](t[1], t[2]))
        self.downloads = downloads.Downloads(settings, lambda job: self._bridge.done.emit(
            (lambda *_: self._job_ended(job), None, None)))
        self.wing = Wing(self)                   # the search windows, outside to the right
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().dataChanged.connect(self.wing.clipboard_changed)
        self.notice = ""                         # bottom left: progress, and "... is ready"
        self.notice_a = anim.Prop(0.0, look.COLOR_MS * 2, look.css_ease)
        self.notice_until = 0.0
        self.notice_target: Path | None = None

        self.search = QLineEdit(self)
        self.search.setFrame(False)
        self.search.setPlaceholderText("search")
        self.search.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {look.TEXT.name()}; border: none;"
            f" border-bottom: 1px solid {look.alpha(look.FAINT, 0.7).name(QColor.NameFormat.HexArgb)};"
            f" padding: 0px; }}")
        from PyQt6.QtGui import QPalette
        pal = self.search.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, look.FAINT)
        self.search.setPalette(pal)
        self.search.setFont(paint.font(look.LIST_PX))
        self.search.returnPressed.connect(self._search_go)
        # the leaf: switches search sources on and off
        self.leaf_k = anim.Prop(0.0, look.PANEL_IN_MS)
        self.leaf_hover = anim.Prop(0.0, look.COLOR_MS, look.css_ease)
        self.leaf_rows: list[tuple[str, str, bool]] = []
        self._place_search()

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
        self.brand_k.set(1.0 if opened else 0.0)
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
                self.start_link(text, into=cat.home)
                self.refresh_panel()

    # --- adding files ------------------------------------------------------------------
    def add_file(self, cat: library.Category, src: Path) -> None:
        if src.suffix.lower() == ".torrent":
            self.start_link(str(src), into=cat.home)
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
                if ok and f.download:
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

    # --- search --------------------------------------------------------------------
    def _place_search(self) -> None:
        w, h = self.width(), self.height()
        sw = 130
        self.search.setGeometry(int(w - 14 - sw), int(h - 14 - 20), sw, 20)

    def resizeEvent(self, ev) -> None:
        self._place_search()
        if self.wing.isVisible():
            self.wing.follow()
        super().resizeEvent(ev)

    def _search_go(self) -> None:
        query = self.search.text().strip()
        if not query:
            return
        from ..sources import plugins
        if plugins.is_plugin_ref(query):
            self.search.clear()
            self.add_plugin(query)
            return
        self.hide_entry()
        if self.panel:
            self.panel.cancel_adding()
        wing = self.wing
        wing.open_results(query)
        names = list(self.settings["sources"])
        off = set(self.settings["sources_off"])
        self.close_leaf()

        def done(res, err):
            if wing.query != query:
                return
            if err or res is None:
                wing.set_results([], f"The search did not work: {err}")
                return
            note = "" if res.results else ("Nothing found." if not res.errors else " ".join(res.errors))
            wing.set_results(res.results, note)
        self.run(lambda: sources.search(query, names, off), done)

    def add_plugin(self, ref: str) -> None:
        """A search plugin's address (or file) given to Bramble: keep it for searching."""
        from ..sources import plugins
        self._say("adding to search…", secs=30)

        def done(name, err):
            if err:
                self._say(f"could not add it: {err}", secs=12)
            else:
                self._say(f"added {name} to search", secs=8)
        self.run(lambda: plugins.install(ref), done)

    # --- the leaf: search sources on and off ---------------------------------------
    def _leaf_centre(self) -> QPointF:
        g = self.search.geometry()
        return QPointF(g.left() - 13, g.center().y() + 1)

    def _leaf_card(self) -> QRectF:
        g = self.search.geometry()
        n = max(1, len(self.leaf_rows))
        h = min(n, 8) * look.ROW + 2 * 10
        w = 190
        return QRectF(g.right() - w, g.top() - 12 - h, w, h)

    def toggle_leaf(self) -> None:
        if self.leaf_k.target > 0.5:
            self.close_leaf()
            return
        self.leaf_rows = sources.catalog(self.settings)
        self.leaf_k.set(1.0, look.PANEL_IN_MS)

    def close_leaf(self) -> None:
        self.leaf_k.set(0.0, look.PANEL_OUT_MS)

    def flip_source(self, key: str) -> None:
        if key.startswith("builtin:"):
            name = key.split(":", 1)[1]
            chosen = list(self.settings["sources"])
            self.settings["sources"] = ([n for n in chosen if n != name] if name in chosen
                                        else chosen + [name])
        else:
            off = list(self.settings["sources_off"])
            self.settings["sources_off"] = ([k for k in off if k != key] if key in off
                                            else off + [key])
        self.leaf_rows = sources.catalog(self.settings)

    def _paint_leaf(self, p: QPainter) -> None:
        from PyQt6.QtGui import QPainterPath, QPen
        c = self._leaf_centre()
        k = self.leaf_k.value
        col = look.mix(look.FAINT, look.TEXT, max(self.leaf_hover.value, k))
        # a small leaf: two curves from stem to tip, a midrib, and a short stem
        base, tip = QPointF(c.x() - 4, c.y() + 4), QPointF(c.x() + 4.5, c.y() - 4.5)
        path = QPainterPath(base)
        path.quadTo(QPointF(c.x() - 5, c.y() - 5), tip)
        path.quadTo(QPointF(c.x() + 5, c.y() + 5), base)
        pen = QPen(col)
        pen.setWidthF(0.9)
        p.save()
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.drawLine(base, QPointF(c.x() + 2, c.y() - 2))
        p.drawLine(base, QPointF(base.x() - 2, base.y() + 2))
        p.restore()
        self.regions.append((QRectF(c.x() - 10, c.y() - 10, 20, 20), "leaf", self.toggle_leaf))
        if k <= 0.01:
            return
        card = self._leaf_card()
        r = card.translated(0, 10 * (1 - look.ease(k)))
        p.save()
        p.setOpacity(k)
        for s_ in range(look.SHADOW, 0, -1):
            a = 0.05 * (1 - s_ / (look.SHADOW + 1))
            p.fillPath(paint.rounded(r.adjusted(-s_, -s_ + 2, s_, s_ + 2), look.RADIUS + s_),
                       QColor(0, 0, 0, int(255 * a)))
        p.setClipPath(paint.rounded(r), Qt.ClipOperation.IntersectClip)
        self.bg.paint(p, r, look.GLASS_SCRIM, blur=True, canvas=self.canvas())
        y = r.top() + 10
        if not self.leaf_rows:
            paint.draw_text(p, r.left() + 12, y + 4, "none added yet", look.NOTE_PX, look.FAINT)
        for key, name, on in self.leaf_rows[:8]:
            hv = 1.0 if self.hover_key == "src:" + key else 0.0
            colr = look.mix(look.TEXT if on else look.FAINT, look.TEXT, hv)
            label = paint.elide(name, look.LIST_PX, r.width() - 46)
            paint.draw_text(p, r.left() + 12, y + 3, label, look.LIST_PX, colr, glow=hv * 0.6)
            # Hawthorn's ring: filled when on, a faint circle when off
            cx, cy = r.right() - 16, y + look.ROW / 2 + 0.5
            p.save()
            if on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(232, 234, 238, int(0.95 * 255)))
            else:
                ring = QPen(QColor(141, 148, 162, int(0.45 * 255)))
                ring.setWidthF(1.0)
                p.setPen(ring)
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 3.4, 3.4)
            p.restore()
            if k > 0.5:
                self.regions.append((QRectF(r.left() + 4, y, r.width() - 8, look.ROW), "src:" + key,
                                     lambda key=key: self.flip_source(key)))
            y += look.ROW
        p.restore()

    def choose_result(self, r, row_y: float) -> None:
        """A result clicked: its page opens in the browser, and the download window offers a
        box for the magnet link the person copies there. Nothing downloads until they do."""
        existing = next((j for j in self.downloads.jobs if getattr(j, "source_link", "") == r.link), None)
        if existing is not None:
            self.wing.open_download(r, row_y, existing)
            return
        page = r.page or (r.link if r.link.startswith(("http://", "https://"))
                          and not r.link.lower().split("?")[0].endswith(".torrent") else "")
        if page:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(page))
        # no page to open (the source gives the link itself): offer that link instead
        self.wing.open_paste(r, row_y, prefill="" if page else r.link)

    def start_link(self, link: str, title: str = "", into: Path | None = None, source_link: str = ""):
        """Every link Bramble downloads goes through here: into a holding folder, then the
        checks (vet.py), then into the library (or `into`)."""
        import uuid
        marrow = self._marrow()
        holding = marrow / ".holding" / uuid.uuid4().hex[:10]
        title = kinds._tidy(title) if title else downloads.title_of(link)
        job = self.downloads.start(link.strip(), holding, marrow=marrow, title=title, into=into)
        job.source_link = source_link
        self._say(f"{title} is downloading")
        return job

    def play_landed(self, path: Path) -> None:
        roots = library.library_roots(self.settings)
        items = []
        for c in library.categories(self.settings):
            if any(f in path.parents or f == path for f in c.folders):
                items = library.scan_category(c)
        hit = next((i for i in items if i.path == path or i.path in path.parents
                    or path in i.path.parents), None)
        if hit is None:
            return
        settings = self.settings

        def work():
            return launcher.try_ways(hit, launcher.ways_for(hit, settings))
        self.run(work, lambda out, err: self._say(
            f"{hit.title} did not open" if (err or not out.ok) else f"opened {hit.title}"))

    def get_tool(self, tool_id: str) -> None:
        def work():
            rel, errors = fetch.latest(tool_id)
            if rel is None:
                raise OSError("No download site answered.")
            fetch.install(rel, self._tools_destination())
            return True
        self.run(work, lambda ok, err: (self.downloads.retry_failed() if ok else None,
                                         self._say(f"could not get {tool_id}: {err}" if err else
                                                   f"{tool_id} is ready")))

    def escape_search(self) -> None:
        if self.wing.dl_card.tl.opening:
            self.wing.close_download()
        elif self.wing.results_card.tl.opening:
            self.wing.close_results()

    def moveEvent(self, ev) -> None:
        if self.wing.isVisible():
            self.wing.follow()
        super().moveEvent(ev)

    def _marrow(self) -> Path:
        """The library that downloads are filed into: the drive's when it is plugged in."""
        roots = library.library_roots(self.settings)
        return roots[0] if roots else paths.local_marrow()

    def keep_held(self, job):
        self.run(lambda: self.downloads.keep_anyway(job), lambda *_: self._job_ended(job))

    def discard_held(self, job):
        self.downloads.throw_away(job)
        self.wing.close_download()

    def _job_ended(self, job) -> None:
        if getattr(job, "stage", "") == "ready":
            name = job.title
            self._say(f"{name} is ready", target=job.landed)
            notify.send("bramble", f"{name} is ready")
        elif getattr(job, "stage", "") == "held":
            self._say(f"{job.title} is being held")
        self.refresh_panel()

    def _say(self, text: str, target: Path | None = None, secs: float = 8.0) -> None:
        self.notice = text
        self.notice_target = target
        self.notice_until = anim.now() + secs
        self.notice_a.set(1.0)

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
        index = self.rows.index(row)
        top = self._row_y(index) + look.ROW + 12
        w, h = self.width(), self.height()
        height = max(look.ROW * 2 + 2 * look.CARD_PAD, h - top - look.CARD_BOTTOM)
        return QRectF(look.CARD_MARGIN, top, w - 2 * look.CARD_MARGIN, height)

    # --- frame ----------------------------------------------------------------------
    def _tick(self) -> None:
        self.bg.tick()
        self.wing.tick()
        if self.returning and self.timeline.position() <= look.CARD_OPEN[0]:
            self.returning = False     # the card has folded away: now the lines come back
            self._settle()
        if self.panel and self.timeline.shut and self.open_row is None and not self.returning:
            self.panel = None
            self.shown_row = None
        self.update()
        busy = (self.timeline.moving or any(r.moving() for r in self.rows) or self.brand_a.moving or self.brand_k.moving or self.close_hover.moving or self.returning
                or self.notice_a.moving or any(not j.finished for j in self.downloads.jobs)
                or self.leaf_k.moving or self.leaf_hover.moving
                or self.wing.moving()
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
        self.bg.paint(p, full, canvas=self.canvas())
        self.regions = []
        self._paint_brand(p)
        self._paint_rows(p)
        self._paint_card(p)
        self._paint_notice(p)
        self._paint_leaf(p)
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

    def canvas(self) -> QRectF:
        """One picture canvas for Bramble and its side windows, so the picture runs on."""
        return QRectF(0, 0, self.width() + WING_W, self.height() + WING_EXTRA)

    def _paint_brand(self, p: QPainter) -> None:
        """At rest where _brand_origin puts it. A category open: the site's
        translate(-0.5rem, -1rem) scale(0.85) about its top left, at the name's size."""
        x, y = self._brand_origin()
        k = self.brand_k.value
        unit = look.BRAND_PX / 5.2
        p.save()
        p.translate(x - 0.5 * unit * k, y - 1.0 * unit * k)
        s = 1 - 0.15 * k
        p.scale(s, s)
        paint.draw_text(p, 0, 0, "bramble", look.BRAND_PX, look.alpha(look.TEXT, self.brand_a.value),
                        look.BRAND_WEIGHT, look.BRAND_TRACK)
        p.restore()

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

    def _paint_notice(self, p: QPainter) -> None:
        """Bottom left, in Hawthorn's footer place: what is downloading, and what is ready."""
        active = [j for j in self.downloads.jobs if j.marrow is not None and not j.finished]
        if active and anim.now() > self.notice_until:
            j = active[0]
            more = f"  +{len(active) - 1}" if len(active) > 1 else ""
            self.notice = f"{j.title}  {j.state_text}{more}"
            self.notice_target = None
            self.notice_a.set(1.0)
        elif not active and anim.now() > self.notice_until:
            self.notice_a.set(0.0)
        a = self.notice_a.value
        if a <= 0.01 or not self.notice:
            return
        h = self.height()
        width = self.width() - 14 - 130 - 14 - 14
        # wraps upward (up to four lines) rather than cutting a reason off
        from .wing import _wrap
        lines = _wrap(self.notice, look.NOTE_PX, width)[:4]
        hv = 1.0 if self.hover_key == "notice" else 0.0
        col = look.alpha(look.mix(look.DIM, look.TEXT, hv), a)
        tw = 0.0
        for i, line in enumerate(reversed(lines)):
            tw = max(tw, paint.draw_text(p, 14, h - 14 - 16 - 15 * i, line, look.NOTE_PX, col))
        if self.notice_target is not None:
            target = self.notice_target
            self.regions.append((QRectF(14, h - 34, tw + 4, 20), "notice",
                                 lambda t=target: self._open_landed(t)))

    def _open_landed(self, target: Path) -> None:
        """Clicking "... is ready": open the category it went into."""
        try:
            name = target.relative_to(self._marrow()).parts[0]
        except ValueError:
            return
        row = next((r for r in self.rows if r.cat and r.cat.name == name), None)
        if row is None:
            self.set_categories(library.categories(self.settings))
            row = next((r for r in self.rows if r.cat and r.cat.name == name), None)
        if row is not None and self.open_row is not row:
            if self.open_row is not None:
                self.close_category()
            QTimer.singleShot(1300 if self.shown_row else 0, lambda: self.toggle(row))

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
        self.bg.paint(p, r, look.GLASS_SCRIM, blur=True, canvas=self.canvas())
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
            self.leaf_hover.set(1.0 if key == "leaf" else 0.0)
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
        if self.leaf_k.target > 0.5 and not (key == "leaf" or (key or "").startswith("src:")):
            self.close_leaf()
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
        if ev.key() == Qt.Key.Key_Escape and self.search.hasFocus():
            self.search.clear()
            self.setFocus()
            return
        if ev.key() == Qt.Key.Key_Escape and self.leaf_k.target > 0.5:
            self.close_leaf()
            return
        if ev.key() == Qt.Key.Key_Escape and (self.wing.results_card.tl.opening
                                               or self.wing.dl_card.tl.opening):
            self.escape_search()
            return
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
        from ..sources import plugins
        urls = ev.mimeData().urls() if ev.mimeData().hasUrls() else []
        if urls and (self.open_row is not None or all(
                plugins.is_plugin_ref(u.toLocalFile() or u.toString()) for u in urls)):
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        from ..sources import plugins
        rest = []
        for url in ev.mimeData().urls():
            ref = url.toLocalFile() or url.toString()
            if plugins.is_plugin_ref(ref):
                self.add_plugin(ref)        # a search plugin, wherever it is dropped
            else:
                rest.append(url)
        if not rest or not self.panel:
            return
        for url in rest:
            if url.isLocalFile():
                self.add_file(self.panel.category, Path(url.toLocalFile()))
            else:
                self.start_link(url.toString(), into=self.panel.category.home)
        self.refresh_panel()

    def closeEvent(self, ev) -> None:
        self.downloads.stop_all()
        self.wing.close()
        super().closeEvent(ev)
