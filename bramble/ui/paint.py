"""Type and small drawing helpers: hairline text, its hover glow, rounded clips."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter,
                         QPainterPath)

from . import look

ASSETS = Path(__file__).resolve().parent / "assets"
_family = look.FAMILY


def load_fonts() -> None:
    """Bundle Ubuntu Sans so Windows draws the same hairline type as Linux."""
    global _family
    fid = QFontDatabase.addApplicationFont(str(ASSETS / "fonts" / "UbuntuSans.ttf"))
    fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    if fams:
        _family = fams[0]


@lru_cache(maxsize=64)
def font(px: float, weight: int = look.MENU_WEIGHT, track_em: float = 0.0) -> QFont:
    f = QFont(_family)
    f.setPixelSize(max(1, round(px)))
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    # greyscale smoothing, as the site's -webkit-font-smoothing: antialiased
    f.setStyleStrategy(QFont.StyleStrategy(QFont.StyleStrategy.PreferAntialias
                                           | QFont.StyleStrategy.NoSubpixelAntialias))
    if track_em:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, track_em * px)
    return f


def width(text: str, f: QFont) -> float:
    return QFontMetricsF(f).horizontalAdvance(text)


def ascent(f: QFont) -> float:
    return QFontMetricsF(f).ascent()


def text_height(f: QFont) -> float:
    m = QFontMetricsF(f)
    return m.ascent() + m.descent()


@lru_cache(maxsize=256)
def _glow_image(text: str, px: int, weight: int, track: float, radius: int) -> QImage:
    """The text in the glow colour, blurred: drawn small and scaled back up."""
    f = font(px, weight, track)
    m = QFontMetricsF(f)
    pad = radius * 2
    w = int(m.horizontalAdvance(text) + pad * 2) + 2
    h = int(m.ascent() + m.descent() + pad * 2) + 2
    shrink = max(2, radius // 2)
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(f)
    p.setPen(QColor(look.GLOW.red(), look.GLOW.green(), look.GLOW.blue()))
    # thicken the hairline so the halo has something to spread
    for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
        p.drawText(QPointF(pad + dx, pad + m.ascent() + dy), text)
    p.end()
    small = img.scaled(max(1, w // shrink), max(1, h // shrink),
                       Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    small = small.scaled(max(1, w // (shrink * 2)), max(1, h // (shrink * 2)),
                         Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return small.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)


def draw_text(p: QPainter, x: float, y: float, text: str, px: float, color: QColor,
              weight: int = look.MENU_WEIGHT, track: float = 0.0, glow: float = 0.0) -> float:
    """Text with its top-left at (x, y). glow 0..1 fades in the site's 12px halo.
    Returns the text's width."""
    f = font(px, weight, track)
    if glow > 0.01:
        img = _glow_image(text, round(px), weight, track, look.GLOW_PX)
        pad = look.GLOW_PX * 2
        p.save()
        p.setOpacity(p.opacity() * glow * look.GLOW.alphaF() * 2.2)
        p.drawImage(QPointF(x - pad, y - pad), img)
        p.restore()
    p.setFont(f)
    p.setPen(color)
    p.drawText(QPointF(x, y + ascent(f)), text)
    return width(text, f)


def elide(text: str, px: float, max_w: float, weight: int = look.MENU_WEIGHT) -> str:
    return QFontMetricsF(font(px, weight)).elidedText(text, Qt.TextElideMode.ElideRight, max_w)


def rounded(rect: QRectF, r: float = look.RADIUS) -> QPainterPath:
    path = QPainterPath()
    r = min(r, rect.width() / 2, rect.height() / 2)
    path.addRoundedRect(rect, r, r)
    return path
