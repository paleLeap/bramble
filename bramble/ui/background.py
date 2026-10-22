"""paleleap.com's background: six pictures, one showing at a time, cross-fading
every HOLD+FADE ms, each drifting on its own slow pan the whole time, under the
#0c0d10 scrim.

Same pictures as the site (assets/bg, pre-blurred, 1600x900). Pans follow the
site's nth-child rules: every layer "a", even ones "b", every third "c", every
fifth "d" (later rules win, as in CSS).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, QSizeF, Qt
from PyQt6.QtGui import QPainter, QPixmap

from . import anim, look

BG_DIR = Path(__file__).resolve().parent / "assets" / "bg"
ORDER = ["mountain-stars.jpg", "harbour.jpg", "peaks-dusk.jpg", "tower-night.jpg",
         "ridges.jpg", "skyline.jpg"]


def _pan_for(i: int) -> tuple:
    n = i + 1
    key = "a"
    if n % 2 == 0:
        key = "b"
    if n % 3 == 0:
        key = "c"
    if n % 5 == 0:
        key = "d"
    return look.PANS[key]


class Background:
    def __init__(self):
        self.sources = [BG_DIR / n for n in ORDER if (BG_DIR / n).exists()]
        self.raw = [QPixmap(str(p)) for p in self.sources]
        self.sized: list[QPixmap] = []
        self.size = QSizeF(0, 0)
        self.born = anim.now()
        self.at = 0
        self.fades = [anim.Prop(1.0 if i == 0 else 0.0, look.BG_FADE_MS, lambda t: t)
                      for i in range(len(self.raw))]
        self.last_step = anim.now()

    def tick(self) -> None:
        if len(self.raw) < 2:
            return
        period = (look.BG_HOLD_MS + look.BG_FADE_MS) / 1000
        if anim.now() - self.last_step >= period:
            self.last_step = anim.now()
            self.fades[self.at].set(0.0)
            self.at = (self.at + 1) % len(self.raw)
            self.fades[self.at].set(1.0)

    def _resize(self, w: float, h: float) -> None:
        if self.size == QSizeF(w, h):
            return
        self.size = QSizeF(w, h)
        # Cover the window, then the site's 1.14 so the pan never shows an edge.
        out = []
        for pm in self.raw:
            k = max(w / pm.width(), h / pm.height()) * look.BG_SCALE
            out.append(pm.scaled(int(pm.width() * k) + 2, int(pm.height() * k) + 2,
                                 Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))
        self.sized = out

    def paint(self, p: QPainter, rect: QRectF, scrim: float = look.SCRIM) -> None:
        """Fill `rect` (window coordinates) with the pictures and the scrim. The
        pictures are laid out against the whole window, so a smaller rect shows the
        same picture continuing, as Hawthorn's cards do."""
        win = p.window()
        w, h = win.width(), win.height()
        p.fillRect(rect, look.BG)
        if self.raw:
            self._resize(w, h)
            t = anim.now() - self.born
            p.save()
            p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
            for i, pm in enumerate(self.sized):
                a = self.fades[i].value
                if a <= 0.002:
                    continue
                fx, fy, tx, ty, secs = _pan_for(i)
                cyc = (t / secs) % 2.0
                k = look.ease_in_out(cyc if cyc <= 1 else 2 - cyc)     # alternate
                # translate(%) applies to the layer box (the window), inside scale(1.14)
                dx = (fx + (tx - fx) * k) * w * look.BG_SCALE
                dy = (fy + (ty - fy) * k) * h * look.BG_SCALE
                x = (w - pm.width()) / 2 + dx
                y = (h - pm.height()) / 2 + dy
                p.setOpacity(a)
                p.drawPixmap(int(x), int(y), pm)
            p.restore()
        p.save()
        p.setOpacity(scrim)
        p.fillRect(rect, look.BG)
        p.restore()
