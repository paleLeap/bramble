"""What an opened category shows inside its card.

A list of cleaned-up titles. Clicking one shows its info (a small thumbnail and
the stats behind it); clicking it again plays it. TV shows are "+ show" lines
that open onto their episodes, as Hawthorn's lines open onto theirs. The last
line is "+": paste a link or pick a file to add to this category.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QPen

from .. import checks, guide, kinds, launcher, probe
from ..library import Item
from . import anim, look, paint

ROW = look.ROW


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def duration(secs: float) -> str:
    m = int(secs // 60)
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


@dataclass
class Entry:
    """One line in the card."""
    key: str
    title: str
    item: Item | None = None
    children: list["Entry"] = field(default_factory=list)   # a show's episodes
    depth: int = 0
    download: object | None = None                           # downloads.Job
    hover: anim.Prop = field(default_factory=lambda: anim.Prop(0.0, look.COLOR_MS, look.css_ease))

    @property
    def group(self) -> bool:
        return bool(self.children)


@dataclass
class Info:
    """What the first click shows."""
    lines: list[str] = field(default_factory=list)
    thumb: QImage | None = None
    issues: list[checks.Issue] = field(default_factory=list)
    hint: str = ""
    error: list[str] = field(default_factory=list)          # after a failed open
    error_fixes: list[checks.Fix] = field(default_factory=list)
    busy: bool = False
    pr: probe.Probe | None = None


def _plain(html: str) -> str:
    first = re.split(r"</p>|</li>", html, maxsplit=1)[0]
    text = re.sub(r"<[^>]+>", "", first)
    return re.sub(r"\s+", " ", text).replace("&gt;", ">").replace("&lt;", "<").strip()


def stat_lines(item: Item, pr: probe.Probe | None) -> list[str]:
    out: list[str] = []
    k = item.kind
    if k in ("movie", "episode") and pr and pr.ok:
        first = []
        if item.episode:
            first.append(f"S{item.episode.season:02d}E{item.episode.number:02d}")
        if item.year:
            first.append(item.year)
        if pr.resolution:
            first.append(pr.resolution + (" HDR" if pr.hdr else ""))
        if pr.duration:
            first.append(duration(pr.duration))
        out.append("  ·  ".join(first))
        second = []
        if pr.audio:
            a = pr.audio[0]
            ch = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(a["channels"], f"{a['channels']} ch")
            second.append(f"{a['codec'].upper()} {ch}")
        langs = sorted({(s.language or "?")[:3].lower() for s in pr.subs})
        if langs:
            second.append("subtitles " + ", ".join(langs))
        elif item.sidecar_subs:
            second.append("subtitles beside it")
        if second:
            out.append("  ·  ".join(second))
    elif k == "music":
        bits = [b for b in (item.album, duration(pr.duration) if pr and pr.ok and pr.duration else "") if b]
        if bits:
            out.append("  ·  ".join(bits))
    elif k == "rom" and item.system:
        out.append(item.system.name)
    elif k == "game_windows":
        out.append("windows")
    elif k == "game_linux":
        out.append("linux")
    elif item.year:
        out.append(item.year)
    out.append(human_size(item.size))
    return [l for l in out if l]


class Panel:
    """Lays out and draws an open category's card contents; answers its clicks."""

    def __init__(self, host, category):
        self.host = host                      # the window: repaint, run(), settings, play()
        self.category = category
        self.entries: list[Entry] = []
        self.open_groups: set[str] = set()
        self.selected: str | None = None
        self.infos: dict[str, Info] = {}
        self.scroll = 0.0
        self.content_h = 0.0
        self.mode = "list"                    # list, adding, picking
        self.pick_dir: Path = Path.home()
        self.pick_rows: list[tuple[str, Path | None]] = []
        self.pick_hover = anim.Prop(0.0)
        self.hover_key: str | None = None
        self.add_hover = anim.Prop(0.0, look.MARK_MS, look.css_ease)
        self.close_hover = anim.Prop(0.0, look.COLOR_MS, look.css_ease)
        self.regions: list[tuple[QRectF, str, Callable[[], None]]] = []

    # --- content ------------------------------------------------------------------
    def set_items(self, items: list[Item], jobs: list) -> None:
        old_hover = {e.key: e.hover for e in self._walk(self.entries)}
        entries: list[Entry] = []
        if self.category.kind == "tv":
            shows: dict[str, list[Item]] = {}
            for it in items:
                show = it.episode.show if it.episode else it.title
                shows.setdefault(show, []).append(it)
            for show in sorted(shows, key=str.lower):
                eps = sorted(shows[show], key=lambda i: ((i.episode.season, i.episode.number)
                                                         if i.episode else (0, 0), i.title))
                kids = [Entry(it.key, it.display, it, depth=1) for it in eps]
                entries.append(Entry("show:" + show, show, None, kids))
        else:
            for it in sorted(items, key=lambda i: i.display.lower()):
                entries.append(Entry(it.key, it.display, it))
        for job in jobs:
            entries.append(Entry("job:" + job.id, job.title, None, download=job))
        for e in self._walk(entries):
            if e.key in old_hover:
                e.hover = old_hover[e.key]
        self.entries = entries

    @staticmethod
    def _walk(entries):
        for e in entries:
            yield e
            yield from e.children

    def visible(self) -> list[Entry]:
        out = []
        for e in self.entries:
            out.append(e)
            if e.group and e.key in self.open_groups:
                out.extend(e.children)
        return out

    def moving(self) -> bool:
        return (any(e.hover.moving for e in self._walk(self.entries)) or self.add_hover.moving
                or self.close_hover.moving or any(i.busy for i in self.infos.values())
                or any(e.download and not e.download.finished for e in self.entries))

    # --- clicks -----------------------------------------------------------------
    def click_entry(self, e: Entry) -> None:
        if e.group:
            if e.key in self.open_groups:
                self.open_groups.discard(e.key)
            else:
                self.open_groups.add(e.key)
            return
        if e.download is not None:
            self.selected = None if self.selected == e.key else e.key
            return
        if self.selected == e.key and e.item is not None:
            self.host.play(e.item, self)          # second click: play
            return
        self.selected = e.key
        if e.item is not None and e.key not in self.infos:
            self._load_info(e.item)

    def _load_info(self, item: Item) -> None:
        info = Info(busy=True)
        self.infos[item.key] = info

        def work():
            from .. import thumbs
            pr = probe.probe(item.path) if item.kind in ("movie", "episode", "music") else None
            thumb = thumbs.thumbnail(item, pr)
            issues = [i for i in checks.before_open(item, pr)
                      if i.level in ("warn", "bad") or any(f.run for f in i.fixes)]
            return pr, thumb, issues

        def done(res, err):
            info.busy = False
            if err or res is None:
                info.lines = stat_lines(item, None)
                return
            pr, thumb, issues = res
            info.pr = pr
            info.lines = stat_lines(item, pr)
            info.thumb = QImage(str(thumb)) if thumb else None
            info.issues = issues
            hints = [f.guide for i in issues for f in i.fixes if f.guide]
            if hints and hints[0] in guide.BY_ID:
                info.hint = _plain(guide.BY_ID[hints[0]].body)
        self.host.run(work, done)

    def opened(self, item: Item, outcome) -> None:
        info = self.infos.setdefault(item.key, Info())
        info.busy = False
        if outcome.ok:
            info.error, info.error_fixes = [], []
            return
        info.error = [f"{a.way}: {a.detail or 'did not start'}" for a in outcome.attempts]
        info.error_fixes = [f for i in checks.after_failure(item, outcome) for f in i.fixes
                            if not f.guide]
        info.hint = _plain(guide.BY_ID["nothing-opens"].body)

    # --- layout and drawing -------------------------------------------------------
    def paint(self, p: QPainter, card: QRectF, opacity: float, shift: float) -> None:
        """Draw inside `card` (already clipped). shift slides the contents in from the right."""
        self.regions = []
        if opacity <= 0.002:
            return
        p.save()
        p.setOpacity(opacity)
        inner = card.adjusted(14, 12, -14, -12)
        # the card's own close mark, top right
        cx = QRectF(card.right() - 26, card.top() + 2, 24, 22)
        p.setOpacity(opacity)
        c = look.mix(look.FAINT, look.TEXT, self.close_hover.value)
        paint.draw_text(p, cx.left() + 7, cx.top() + 3, "×", 13, c)
        self.regions.append((cx, "card-close", self.host.close_category))
        p.setClipRect(inner.adjusted(-8, 0, 8, 0), Qt.ClipOperation.IntersectClip)
        x0 = inner.left() + shift
        y = inner.top() - self.scroll
        width = inner.width() - 18
        if self.mode == "picking":
            y = self._paint_picker(p, x0, y, width, inner)
        else:
            for e in self.visible():
                y = self._paint_entry(p, e, x0, y, width, inner)
            y = self._paint_add(p, x0, y, width, inner)
        self.content_h = y + self.scroll - inner.top()
        self.view_h = inner.height()
        p.restore()

    def _paint_entry(self, p, e: Entry, x0, y, width, inner) -> float:
        x = x0 + e.depth * look.HANG
        h = e.hover.value
        sel = self.selected == e.key
        if e.group:
            opened = e.key in self.open_groups
            mark = "−" if opened else "+"
            mcol = look.mix(look.FAINT, look.DIM, max(h, 1.0 if opened else 0.0))
            col = look.TEXT if opened else look.mix(look.FAINT, look.TEXT, h)
            paint.draw_text(p, x, y + 3, mark, look.LIST_PX, mcol)
            title = paint.elide(e.title, look.LIST_PX, width - look.MARKER_W)
            tw = paint.draw_text(p, x + look.MARKER_W, y + 3, title, look.LIST_PX, col, glow=h)
            self._region(QRectF(x, y, look.MARKER_W + tw + 6, ROW), e, inner)
            return y + ROW
        col = look.TEXT if (sel or e.download) else look.mix(look.DIM, look.TEXT, h)
        title = paint.elide(e.title, look.LIST_PX, width - (60 if e.download else 0))
        tw = paint.draw_text(p, x, y + 3, title, look.LIST_PX, col, glow=max(h, 0.0))
        self._region(QRectF(x, y, max(tw + 6, 40), ROW), e, inner)
        if e.download is not None:
            job = e.download
            state = job.state_text
            sc = look.BAD if job.failed else look.FAINT
            paint.draw_text(p, x + tw + 10, y + 6, state, look.STATE_PX, sc)
            y += ROW
            if not job.finished:
                self._busy(p, x, y - 4)
                y += 8
            if sel and job.failed:
                fixes = []
                if getattr(job, "needs", ""):
                    fixes = [checks.Fix(f"Download {job.needs} for Bramble", download=job.needs)]
                y = self._error_box(p, x, y, width, [job.error], fixes)
            return y
        y += ROW
        if sel and e.item is not None:
            y = self._paint_info(p, e.item, x, y, width)
        return y

    def _paint_info(self, p, item: Item, x, y, width) -> float:
        info = self.infos.get(item.key)
        if info is None:
            return y
        if info.thumb is not None and not info.thumb.isNull():
            tw = min(128.0, width * 0.6)
            th = tw * info.thumb.height() / max(1, info.thumb.width())
            p.drawImage(QRectF(x, y + 2, tw, th), info.thumb)
            y += th + 8
        for line in info.lines:
            for chunk in self._wrap(line, look.NOTE_PX, width):
                paint.draw_text(p, x, y, chunk, look.NOTE_PX, look.FAINT)
                y += 16
        y += 6
        if info.busy:
            self._busy(p, x, y)
            y += 10
        for iss in info.issues:
            fixes = [f for f in iss.fixes if not f.guide]
            y = self._error_box(p, x, y, width, [iss.title], fixes, item)
        if info.error:
            y = self._error_box(p, x, y, width, info.error, info.error_fixes, item)
        if info.hint and (info.error or info.issues):
            for chunk in self._wrap(info.hint, 12, width):
                paint.draw_text(p, x, y, chunk, 12, look.DIM)
                y += 17
            y += 4
        return y + 6

    def _error_box(self, p, x, y, width, lines: list[str], fixes, item: Item | None = None) -> float:
        wrapped = [c for l in lines for c in self._wrap(l, 12, width - 16)]
        h = 8 + 17 * len(wrapped)
        if fixes:
            h += 18
        box = QRectF(x, y + 2, width, h)
        p.fillRect(box, look.ERR_FILL)
        p.fillRect(QRectF(x, y + 2, 2, h), look.ERR_EDGE)
        ty = y + 6
        for c in wrapped:
            paint.draw_text(p, x + 8, ty, c, 12, look.ERR_TEXT)
            ty += 17
        fx = x + 8
        for f in fixes:
            label = f.label[0].lower() + f.label[1:]
            key = f"fix:{id(f)}"
            hv = 1.0 if self.hover_key == key else 0.0
            w = paint.draw_text(p, fx, ty, label, look.NOTE_PX, look.mix(look.DIM, look.TEXT, hv))
            self.regions.append((QRectF(fx, ty - 2, w + 4, 16), key,
                                 lambda f=f, it=item: self.host.fix(f, it, self)))
            fx += w + 14
        return y + h + 8

    def _paint_add(self, p, x0, y, width, inner) -> float:
        if self.mode == "adding":
            self.host.place_entry(QRectF(x0, y, width - 40, ROW))
            fw = paint.width("file", paint.font(look.NOTE_PX))
            fxr = QRectF(x0 + width - 34, y + 5, fw + 4, 16)
            hv = 1.0 if self.hover_key == "pick" else 0.0
            paint.draw_text(p, fxr.left(), fxr.top(), "file", look.NOTE_PX,
                            look.mix(look.DIM, look.TEXT, hv))
            self.regions.append((fxr, "pick", self.start_picking))
            return y + ROW
        h = self.add_hover.value
        paint.draw_text(p, x0, y + 3, "+", look.LIST_PX, look.mix(look.FAINT, look.DIM, h))
        r = QRectF(x0 - 4, y, look.MARKER_W + 8, ROW)
        if inner.contains(r.center()):
            self.regions.append((r, "add", self.start_adding))
        return y + ROW

    def _paint_picker(self, p, x0, y, width, inner) -> float:
        path = str(self.pick_dir)
        shown = paint.font(look.NOTE_PX)
        from PyQt6.QtGui import QFontMetricsF
        path = QFontMetricsF(shown).elidedText(path, Qt.TextElideMode.ElideLeft, width)
        paint.draw_text(p, x0, y, path, look.NOTE_PX, look.DIM)
        y += 22
        for i, (name, target) in enumerate(self.pick_rows):
            key = f"pick:{i}"
            hv = 1.0 if self.hover_key == key else 0.0
            is_dir = target is None or target.is_dir()
            base = look.DIM if is_dir else look.FAINT
            col = look.mix(base, look.TEXT, hv)
            t = paint.elide(name, look.LIST_PX, width)
            w = paint.draw_text(p, x0, y + 3, t, look.LIST_PX, col, glow=hv)
            r = QRectF(x0, y, w + 6, ROW)
            if inner.contains(r.center()) and target is not None:
                self.regions.append((r, key, lambda t=target: self.pick(t)))
            y += ROW
        return y

    def _region(self, r: QRectF, e: Entry, inner: QRectF) -> None:
        if inner.adjusted(-8, 0, 8, 0).contains(r.center()):
            self.regions.append((r, "entry:" + e.key, lambda e=e: self.click_entry(e)))

    def _busy(self, p, x, y) -> None:
        """Hawthorn's busy bar: a 22x2 piece easing back and forth along a 90px track."""
        p.fillRect(QRectF(x, y, 90, 2), look.alpha(look.FAINT, 0.45))
        phase = (time.monotonic() % 2.2) / 1.1
        if phase > 1:
            phase = 2 - phase
        bx = x + (90 - 22) * look.cosine(phase)
        from PyQt6.QtGui import QColor
        p.fillRect(QRectF(bx, y, 22, 2), QColor(0xe8, 0xea, 0xee, int(0.85 * 255)))

    @staticmethod
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
        return lines or [""]

    # --- hover / wheel ----------------------------------------------------------
    def hover(self, key: str | None) -> None:
        self.hover_key = key
        for e in self._walk(self.entries):
            e.hover.set(1.0 if key == "entry:" + e.key else 0.0)
        self.add_hover.set(1.0 if key == "add" else 0.0)
        self.close_hover.set(1.0 if key == "card-close" else 0.0)

    def wheel(self, dy: float) -> None:
        most = max(0.0, self.content_h - getattr(self, "view_h", 0) + 8)
        self.scroll = max(0.0, min(most, self.scroll - dy))

    # --- adding ---------------------------------------------------------------------
    def start_adding(self) -> None:
        self.mode = "adding"
        self.host.show_entry()

    def start_picking(self) -> None:
        self.host.hide_entry()
        self.mode = "picking"
        self.scroll = 0
        self._list_dir(Path.home())

    def _list_dir(self, d: Path) -> None:
        self.pick_dir = d
        rows: list[tuple[str, Path | None]] = []
        if d.parent != d:
            rows.append(("..", d.parent))
        try:
            kids = sorted((c for c in d.iterdir() if not c.name.startswith(".")),
                          key=lambda c: (not c.is_dir(), c.name.lower()))
        except OSError:
            kids = []
        for c in kids[:400]:
            rows.append((c.name + ("/" if c.is_dir() else ""), c))
        self.pick_rows = rows

    def pick(self, target: Path) -> None:
        if target.is_dir():
            self.scroll = 0
            self._list_dir(target)
            return
        self.mode = "list"
        self.host.add_file(self.category, target)

    def back(self) -> bool:
        """Esc inside the card. True if it used the key."""
        if self.mode in ("adding", "picking"):
            self.mode = "list"
            self.host.hide_entry()
            return True
        if self.selected:
            self.selected = None
            return True
        return False
