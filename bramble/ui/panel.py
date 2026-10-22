"""What an opened category shows inside its card.

A list of plain names. Hovering one grows it to show a small thumbnail and its
resolution, length and subtitles; clicking the name or the thumbnail opens it.
TV shows are "+ show" lines that open onto their episodes. The last line is a
"+", centred under the first letter of the name above it: paste a link or pick
a file to add to this category.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QImage, QPainter

from .. import checks, guide, probe
from ..library import Item
from . import anim, look, paint

ROW = look.ROW
LINE_H = 16          # one line of info text
THUMB_W = 128
THUMB_H = 72         # every thumbnail sits in the same 16:9 box, so every title grows the same
INFO_H = 2 + THUMB_H + 6 + LINE_H + 8


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
    download: object | None = None                           # downloads.Job or CopyJob
    hover: anim.Prop = field(default_factory=lambda: anim.Prop(0.0, look.COLOR_MS, look.css_ease))
    grow: anim.Prop = field(default_factory=lambda: anim.Prop(0.0, look.GROW_MS))   # px of info shown
    turn: anim.Prop = field(default_factory=lambda: anim.Prop(0.0, look.MOVE_MS))   # + -> -

    @property
    def group(self) -> bool:
        return bool(self.children)


@dataclass
class Info:
    """What hovering shows."""
    line: str = ""
    thumb: QImage | None = None
    issues: list[checks.Issue] = field(default_factory=list)
    hint: str = ""
    error: list[str] = field(default_factory=list)          # after a failed open
    error_fixes: list[checks.Fix] = field(default_factory=list)
    busy: bool = False
    loaded: bool = False
    pr: probe.Probe | None = None


def _plain(html: str) -> str:
    first = re.split(r"</p>|</li>", html, maxsplit=1)[0]
    text = re.sub(r"<[^>]+>", "", first)
    return re.sub(r"\s+", " ", text).replace("&gt;", ">").replace("&lt;", "<").strip()


def info_line(item: Item, pr: probe.Probe | None) -> str:
    """Resolution, length, subtitles (user, 2026-10-22: nothing else)."""
    k = item.kind
    bits: list[str] = []
    if k in ("movie", "episode") and pr and pr.ok:
        if pr.resolution:
            bits.append(pr.resolution)
        if pr.duration:
            bits.append(duration(pr.duration))
        if pr.subs or item.sidecar_subs:
            bits.append("subtitles")
    elif k == "music" and pr and pr.ok and pr.duration:
        bits.append(duration(pr.duration))
    elif k == "rom" and item.system:
        bits.append(item.system.name)
    return "  ·  ".join(bits)


class Panel:
    """Lays out and draws an open category's card contents; answers its clicks."""

    def __init__(self, host, category):
        self.host = host
        self.category = category
        self.entries: list[Entry] = []
        self.open_groups: set[str] = set()
        self.infos: dict[str, Info] = {}
        self.scroll = 0.0
        self.content_h = 0.0
        self.view_h = 0.0
        self.mode = "list"                    # list, adding, picking
        self.pick_dir: Path = Path.home()
        self.pick_rows: list[tuple[str, Path | None]] = []
        self.hover_key: str | None = None
        self.add_hover = anim.Prop(0.0, look.MARK_MS, look.css_ease)
        self.close_hover = anim.Prop(0.0, look.COLOR_MS, look.css_ease)
        self.regions: list[tuple[QRectF, str, Callable[[], None]]] = []
        self.note = ""                        # a line shown when a list is empty or searching
        self.searching = False

    # --- content ------------------------------------------------------------------
    def set_items(self, items: list[Item], jobs: list) -> None:
        old = {e.key: e for e in self._walk(self.entries)}
        entries: list[Entry] = []
        if self.category.kind == "tv":
            shows: dict[str, list[Item]] = {}
            for it in items:
                shows.setdefault(it.episode.show if it.episode else it.title, []).append(it)
            for show in sorted(shows, key=str.lower):
                eps = sorted(shows[show], key=lambda i: ((i.episode.season, i.episode.number)
                                                         if i.episode else (0, 0), i.title))
                kids = [Entry(it.key, it.display if it.episode else it.title, it, depth=1) for it in eps]
                entries.append(Entry("show:" + show, show, None, kids))
        else:
            for it in sorted(items, key=lambda i: i.title.lower()):
                entries.append(Entry(it.key, it.title, it))
        for job in jobs:
            entries.append(Entry("job:" + job.id, job.title, None, download=job))
        for e in self._walk(entries):
            if e.key in old:                  # keep animations running across a rescan
                e.hover, e.grow, e.turn = old[e.key].hover, old[e.key].grow, old[e.key].turn
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
        return (any(e.hover.moving or e.grow.moving or e.turn.moving for e in self._walk(self.entries))
                or self.add_hover.moving or self.close_hover.moving
                or any(i.busy for i in self.infos.values())
                or any(e.download and not e.download.finished for e in self.entries))

    # --- clicks -----------------------------------------------------------------
    def click_entry(self, e: Entry) -> None:
        if e.group:
            if e.key in self.open_groups:
                self.open_groups.discard(e.key)
                e.turn.set(0.0)
            else:
                self.open_groups.add(e.key)
                e.turn.set(1.0)
                self.preload()
            return
        if e.item is not None:
            self.host.play(e.item, self)

    def preload(self) -> None:
        """Look inside everything listed, one at a time in the background, so a title
        is ready to open the moment the pointer reaches it."""
        todo = [e.item for e in self._walk(self.entries)
                if e.item is not None and not self.infos.get(e.key, Info()).loaded
                and not self.infos.get(e.key, Info()).busy]
        if not todo:
            return
        for it in todo:
            self.infos.setdefault(it.key, Info()).busy = True

        def work():
            for it in todo:
                info = self.infos[it.key]
                try:
                    pr, thumb, issues = self._gather(it)
                    info.pr, info.line, info.issues = pr, info_line(it, pr), issues
                    info.thumb = QImage(str(thumb)) if thumb else None
                except Exception:
                    pass
                info.busy, info.loaded = False, True
        self.host.run(work)

    @staticmethod
    def _gather(item: Item):
        from .. import thumbs
        pr = probe.probe(item.path) if item.kind in ("movie", "episode", "music") else None
        thumb = thumbs.thumbnail(item, pr)
        issues = [i for i in checks.before_open(item, pr)
                  if i.level in ("warn", "bad") or any(f.run for f in i.fixes)]
        return pr, thumb, issues

    def _load_info(self, item: Item) -> None:
        info = self.infos.setdefault(item.key, Info())
        if info.loaded or info.busy:
            return
        info.busy = True

        def work():
            return self._gather(item)

        def done(res, err):
            info.busy = False
            info.loaded = True
            if err or res is None:
                return
            pr, thumb, issues = res
            info.pr = pr
            info.line = info_line(item, pr)
            info.thumb = QImage(str(thumb)) if thumb else None
            info.issues = issues
        self.host.run(work, done)

    def opened(self, item: Item, outcome) -> None:
        info = self.infos.setdefault(item.key, Info())
        info.busy = False
        if outcome.ok:
            info.error, info.error_fixes, info.hint = [], [], ""
            return
        info.error = [f"{a.way}: {a.detail or 'did not start'}" for a in outcome.attempts]
        info.error_fixes = [f for i in checks.after_failure(item, outcome) for f in i.fixes
                            if not f.guide]
        info.hint = _plain(guide.BY_ID["nothing-opens"].body)

    # --- layout and drawing -------------------------------------------------------
    def natural_height(self) -> float:
        """How tall the card wants to be for what it holds now (padding included)."""
        return self.content_h + 2 * look.CARD_PAD

    def paint(self, p: QPainter, card: QRectF, opacity: float, shift: float) -> None:
        """Draw inside `card` (already clipped). shift slides the contents in from the right."""
        self.regions = []
        p.save()
        p.setOpacity(opacity)
        inner = card.adjusted(look.CARD_PAD, look.CARD_PAD, -look.CARD_PAD, -look.CARD_PAD)
        # the card's own close mark, top right: invisible until hovered (as Hawthorn's)
        cx = QRectF(card.right() - 26, card.top() + 2, 24, 22)
        if self.close_hover.value > 0.01:
            paint.draw_text(p, cx.left() + 7, cx.top() + 3, "×", 13,
                            look.alpha(look.TEXT, self.close_hover.value))
        if opacity > 0.5:
            self.regions.append((cx, "card-close", self.host.close_category))
        p.setClipRect(inner.adjusted(-8, -4, 8, 4), Qt.ClipOperation.IntersectClip)
        x0 = inner.left() + shift
        y = inner.top() - self.scroll
        width = inner.width() - 18
        if self.mode == "picking":
            y = self._paint_picker(p, x0, y, width, inner)
        else:
            last_title = ""
            last_x = x0
            for e in self.visible():
                y = self._paint_entry(p, e, x0, y, width, inner)
                last_title, last_x = e.title, x0 + e.depth * look.HANG
                if e.group:
                    last_x += look.MARKER_W
            if self.searching:
                self._busy(p, x0, y + ROW / 2)
                y += ROW
            elif self.note:
                for chunk in self._wrap(self.note, look.NOTE_PX, width):
                    paint.draw_text(p, x0, y + 4, chunk, look.NOTE_PX, look.FAINT)
                    y += LINE_H
            y = self._paint_add(p, x0, last_x, last_title, y, width, inner)
        self.content_h = y + self.scroll - inner.top()
        self.view_h = inner.height()
        p.restore()

    def _paint_entry(self, p, e: Entry, x0, y, width, inner) -> float:
        x = x0 + e.depth * look.HANG
        h = e.hover.value
        top = y
        if e.group:
            mcol = look.mix(look.FAINT, look.DIM, max(h, e.turn.value))
            f = paint.font(look.LIST_PX)
            paint.draw_marker(p, x + paint.width("+", f) / 2, y + ROW / 2, look.LIST_PX,
                              e.turn.value, mcol)
            col = look.mix(look.FAINT, look.TEXT, max(h, e.turn.value))
            title = paint.elide(e.title, look.LIST_PX, width - look.MARKER_W)
            tw = paint.draw_text(p, x + look.MARKER_W, y + 3, title, look.LIST_PX, col, glow=h)
            self._region(QRectF(x - 4, y, look.MARKER_W + tw + 10, ROW), "entry:" + e.key,
                         lambda e=e: self.click_entry(e), inner)
            return y + ROW
        title = paint.elide(e.title, look.LIST_PX, width - (60 if e.download else 0))
        col = look.mix(look.DIM, look.TEXT, h)
        tw = paint.draw_text(p, x, y + 3, title, look.LIST_PX, col, glow=h)
        if e.download is not None:
            job = e.download
            sc = look.BAD if job.failed else look.FAINT
            paint.draw_text(p, x + tw + 10, y + 6, job.state_text, look.STATE_PX, sc)
        elif e.item is not None and e.item.busy:
            # being written by another program (a torrent downloading straight in here)
            paint.draw_text(p, x + tw + 10, y + 6, "downloading", look.STATE_PX, look.FAINT)
        y += ROW
        # what hovering reveals, grown smoothly into its height
        shown = e.grow.value
        self._region(QRectF(x - 4, top, max(tw + 10, width * 0.6), ROW + shown), "entry:" + e.key,
                     lambda e=e: self.click_entry(e), inner)
        expanded = self._expanded(e)
        if e.item is not None and expanded:
            self._load_info(e.item)
        if e.download is not None and not e.download.finished:
            self._busy(p, x, y - 4)
            y += 6
        want = self._info_height(e, width) if expanded else 0.0
        e.grow.set(want)
        if shown > 0.5:
            p.save()
            p.setClipRect(QRectF(x - 8, y, width + 16, shown), Qt.ClipOperation.IntersectClip)
            full = max(want, e.grow.a, 1.0)
            p.setOpacity(p.opacity() * look.clamp(shown / full))
            self._paint_info(p, e, x, y, width)
            p.restore()
        return y + shown

    def _expanded(self, e: Entry) -> bool:
        k = self.hover_key or ""
        return k == "entry:" + e.key or k.startswith(f"fix:{e.key}:")

    def _info_height(self, e: Entry, width: float) -> float:
        """The same for every title of a kind, known before anything has loaded, so the
        one closing and the one opening trade height evenly and the list holds still."""
        if e.download is not None:
            if e.download.failed:
                return self._error_h([e.download.error], width,
                                     bool(getattr(e.download, "needs", ""))) + 4
            return 0.0
        if e.item is None:
            return 0.0
        info = self.infos.get(e.key)
        has_thumb = e.item.kind in ("movie", "episode") or (
            info is not None and info.thumb is not None and not info.thumb.isNull())
        h = INFO_H if has_thumb else 2 + LINE_H + 8
        if info is not None:
            for iss in info.issues:
                h += self._error_h([iss.title], width, any(not f.guide for f in iss.fixes))
            if info.error:
                h += self._error_h(info.error, width, bool(info.error_fixes))
                if info.hint:
                    h += 17 * len(self._wrap(info.hint, 12, width)) + 4
        return h

    def _paint_info(self, p, e: Entry, x, y, width) -> None:
        if e.download is not None:
            if e.download.failed:
                needs = getattr(e.download, "needs", "")
                fixes = [checks.Fix(f"Download {needs} for Bramble", download=needs)] if needs else []
                self._error_box(p, e, x, y + 2, width, [e.download.error], fixes, None)
            return
        info = self.infos.get(e.key)
        if info is None:
            return
        y += 2
        box_on = e.item is not None and (e.item.kind in ("movie", "episode") or (
            info.thumb is not None and not info.thumb.isNull()))
        if box_on:
            box = QRectF(x, y, THUMB_W, THUMB_H)
            if info.thumb is not None and not info.thumb.isNull():
                iw, ih = info.thumb.width(), info.thumb.height()
                k = min(THUMB_W / iw, THUMB_H / ih)
                r = QRectF(x, y + (THUMB_H - ih * k) / 2, iw * k, ih * k)
                p.drawImage(r, info.thumb)
            elif info.busy:
                self._busy(p, x, y + THUMB_H / 2)
            # the thumbnail opens it too
            self.regions.append((box, "entry:" + e.key, lambda e=e: self.click_entry(e)))
            y += THUMB_H + 6
        if info.line:
            paint.draw_text(p, x, y, info.line, look.NOTE_PX, look.FAINT)
        y += LINE_H
        for iss in info.issues:
            fixes = [f for f in iss.fixes if not f.guide]
            y = self._error_box(p, e, x, y, width, [iss.title], fixes, e.item)
        if info.error:
            y = self._error_box(p, e, x, y, width, info.error, info.error_fixes, e.item)
            if info.hint:
                for chunk in self._wrap(info.hint, 12, width):
                    paint.draw_text(p, x, y, chunk, 12, look.DIM)
                    y += 17

    def _error_h(self, lines, width, has_fixes) -> float:
        n = sum(len(self._wrap(l, 12, width - 16)) for l in lines)
        return 8 + 17 * n + (18 if has_fixes else 0) + 8

    def _error_box(self, p, e: Entry, x, y, width, lines: list[str], fixes, item) -> float:
        """Hawthorn's .errmark: a faint rose box with a 2px edge, the reason, then fixes."""
        wrapped = [c for l in lines for c in self._wrap(l, 12, width - 16)]
        h = 8 + 17 * len(wrapped) + (18 if fixes else 0)
        p.fillRect(QRectF(x, y + 2, width, h), look.ERR_FILL)
        p.fillRect(QRectF(x, y + 2, 2, h), look.ERR_EDGE)
        ty = y + 6
        for c in wrapped:
            paint.draw_text(p, x + 8, ty, c, 12, look.ERR_TEXT)
            ty += 17
        fx = x + 8
        for i, f in enumerate(fixes):
            label = f.label[0].lower() + f.label[1:]
            key = f"fix:{e.key}:{i}"
            hv = 1.0 if self.hover_key == key else 0.0
            w = paint.draw_text(p, fx, ty, label, look.NOTE_PX, look.mix(look.DIM, look.TEXT, hv))
            self.regions.append((QRectF(fx, ty - 2, w + 4, 16), key,
                                 lambda f=f, it=item: self.host.fix(f, it, self)))
            fx += w + 14
        return y + h + 8

    def _paint_add(self, p, x0, last_x, last_title, y, width, inner) -> float:
        """The "+" that adds a link or a file, centred under the first letter above it."""
        if self.mode == "adding":
            self.host.place_entry(QRectF(last_x, y, width - 40 - (last_x - x0), ROW))
            fw = paint.width("file", paint.font(look.NOTE_PX))
            fxr = QRectF(x0 + width - 34, y + 5, fw + 4, 16)
            hv = 1.0 if self.hover_key == "pick" else 0.0
            paint.draw_text(p, fxr.left(), fxr.top(), "file", look.NOTE_PX,
                            look.mix(look.DIM, look.TEXT, hv))
            self.regions.append((fxr, "pick", self.start_picking))
            return y + ROW
        cx = last_x + paint.first_letter_centre(last_title, look.LIST_PX)
        h = self.add_hover.value
        paint.draw_marker(p, cx, y + ROW / 2, look.LIST_PX, 0.0, look.mix(look.FAINT, look.DIM, h))
        r = QRectF(cx - 10, y, 20, ROW)
        if inner.adjusted(-8, -4, 8, 4).contains(r.center()):
            self.regions.append((r, "add", self.start_adding))
        return y + ROW

    def _paint_picker(self, p, x0, y, width, inner) -> float:
        path = QFontMetricsF(paint.font(look.NOTE_PX)).elidedText(
            str(self.pick_dir), Qt.TextElideMode.ElideLeft, width)
        paint.draw_text(p, x0, y, path, look.NOTE_PX, look.DIM)
        y += 22
        for i, (name, target) in enumerate(self.pick_rows):
            key = f"pick:{i}"
            hv = 1.0 if self.hover_key == key else 0.0
            is_dir = target is None or target.is_dir()
            col = look.mix(look.DIM if is_dir else look.FAINT, look.TEXT, hv)
            w = paint.draw_text(p, x0, y + 3, paint.elide(name, look.LIST_PX, width),
                                look.LIST_PX, col, glow=hv)
            r = QRectF(x0, y, w + 6, ROW)
            if inner.contains(r.center()) and target is not None:
                self.regions.append((r, key, lambda t=target: self.pick(t)))
            y += ROW
        return y

    def _region(self, r: QRectF, key: str, fn, inner: QRectF) -> None:
        if inner.adjusted(-8, -4, 8, 4).intersects(r):
            self.regions.append((r, key, fn))

    def _busy(self, p, x, y) -> None:
        """Hawthorn's busy bar: a 22x2 piece easing back and forth along a 90px track."""
        p.fillRect(QRectF(x, y, 90, 2), look.alpha(look.FAINT, 0.45))
        phase = (time.monotonic() % 2.2) / 1.1
        if phase > 1:
            phase = 2 - phase
        bx = x + (90 - 22) * look.cosine(phase)
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
            on = key == "entry:" + e.key or (key or "").startswith(f"fix:{e.key}:")
            e.hover.set(1.0 if on else 0.0)
        self.add_hover.set(1.0 if key == "add" else 0.0)
        self.close_hover.set(1.0 if key == "card-close" else 0.0)

    def wheel(self, dy: float) -> None:
        most = max(0.0, self.content_h - self.view_h + 8)
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

    def cancel_adding(self) -> bool:
        """Leave the text box or the picker. True if there was one."""
        if self.mode in ("adding", "picking"):
            self.mode = "list"
            self.host.hide_entry()
            return True
        return False

    def back(self) -> bool:
        """Esc inside the card. True if it used the key."""
        return self.cancel_adding()


def _size(n: int) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""
