"""Every number Bramble draws with, taken from paleleap.com (/data/portfolio/css/style.css,
js/main.js, js/backgrounds.js) and Hawthorn (INNARDS/hawthorn/linux/hawthorn.py).

Sizes are in window pixels at Hawthorn's scale: the site's 0.95rem menu line is
Hawthorn's 14px, and the site's rem distances are carried over in proportion
(1rem of the site = 14/0.95/16 = 0.921 of a px here, times 16).
"""
from __future__ import annotations

import math

from PyQt6.QtGui import QColor

# --- colours (site :root, dark) ---------------------------------------------
BG = QColor("#0c0d10")
TEXT = QColor("#e8eaee")
DIM = QColor("#8d94a2")
FAINT = QColor("#565d6b")
GLOW = QColor(232, 234, 238, int(0.22 * 255))        # the hover halo
TEXT_SOFT = 0.55                                      # the name, at rest (user: fainter than the site's 0.72)
TEXT_GHOST = 0.35                                     # the name, once something is open
BAD = QColor("#c98a7a")                               # Hawthorn .state.bad
ERR_TEXT = QColor("#f0c4b8")                          # Hawthorn .errline
ERR_FILL = QColor(227, 160, 143, int(0.12 * 255))     # Hawthorn .errmark
ERR_EDGE = QColor(227, 160, 143, int(0.55 * 255))
LINE = QColor(0x8d, 0x94, 0xa2, int(0.8 * 255))       # Hawthorn's corner lines: DIM at 0.8

# --- background (site) ------------------------------------------------------
SCRIM = 0.88            # .bg::after opacity
GLASS_SCRIM = 0.72      # the opened card: the same pictures, knocked back less
BG_HOLD_MS = 4000
BG_FADE_MS = 3500
BG_SCALE = 1.14
# (from_dx, from_dy, to_dx, to_dy, seconds) as fractions of the layer size; nth-child rules
PANS = {
    "a": (-0.04, -0.02, 0.04, 0.02, 54),
    "b": (0.04, -0.015, -0.04, 0.015, 62),
    "c": (0.015, 0.035, -0.015, -0.035, 48),
    "d": (-0.03, 0.025, 0.03, -0.025, 58),
}

# --- window (Hawthorn) ----------------------------------------------------------
W0, H0, WMIN, HMIN = 300, 394, 260, 220
RADIUS = 4
EDGE = 7                # resize grip on the right and bottom edges
CLOSE_CELL = 32

# --- type ---------------------------------------------------------------------
FAMILY = "Ubuntu Sans"
BRAND_PX = 39
BRAND_WEIGHT = 100
BRAND_TRACK = -0.035    # em
BRAND_POS = (13, 5)
MENU_PX = 14
MENU_WEIGHT = 200
MENU_TRACK = 0.01       # em
LIST_PX = 13
NOTE_PX = 11
STATE_PX = 10

REM = 14 / 0.95         # one site rem at this scale
X0, MENU_TOP, ROW = 34, 70, 23
MARKER_W = 1.1 * REM * 14 / 15.2      # the "+" column: 1.1rem at the menu's size
STEP = 1.4 * REM * 14 / 15.2          # how far the chosen one steps right
SLIDE = 1.75 * REM * 14 / 15.2        # how far the others slide left, and panels slide in
OPEN_SCALE = 1.12
HOVER_SCALE = 1.045
GLOW_PX = 12
HANG = 26               # Hawthorn: children sit 26px in from their parent

# --- motion (site) --------------------------------------------------------------
MOVE_MS = 560           # transform
FADE_MS = 420           # opacity
COLOR_MS = 300          # colour and glow
MARK_MS = 220           # the marker's colour
BRAND_MS = 1000
PANEL_IN_MS = 560
PANEL_OUT_MS = 380
# Opening a category, seconds: the other lines leave first (FADE_MS), then the card
# opens out of the space under the chosen line, then its contents slide in. Closing
# plays the same timeline backwards, and the lines only return once the card is gone.
CARD_OPEN = (0.42, 0.86)
CARD_TEXT = (0.74, 0.98)
CARD_MARGIN = 22        # the card sits this far in from both sides of the window
CARD_PAD = 14
BLUR = 10               # how far the card's view of the background is shrunk to blur it
SHADOW = 10             # px of soft shadow around the card


def _bezier(x1: float, y1: float, x2: float, y2: float):
    def f(t: float) -> float:
        if t <= 0.0:
            return 0.0
        if t >= 1.0:
            return 1.0
        lo, hi = 0.0, 1.0
        for _ in range(24):
            u = (lo + hi) / 2
            x = 3 * (1 - u) ** 2 * u * x1 + 3 * (1 - u) * u ** 2 * x2 + u ** 3
            lo, hi = (u, hi) if x < t else (lo, u)
        u = (lo + hi) / 2
        return 3 * (1 - u) ** 2 * u * y1 + 3 * (1 - u) * u ** 2 * y2 + u ** 3
    return f


ease = _bezier(0.4, 0.0, 0.2, 1.0)          # the site's --ease
css_ease = _bezier(0.25, 0.1, 0.25, 1.0)     # CSS "ease" (colours, glow, the name's colour)
ease_in_out = _bezier(0.42, 0.0, 0.58, 1.0)  # CSS "ease-in-out" (background pans)


def clamp(t: float) -> float:
    return 0.0 if t < 0 else 1.0 if t > 1 else t


def cosine(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * t)


def mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t),
                  round(a.alpha() + (b.alpha() - a.alpha()) * t))


def alpha(c: QColor, a: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, c.alphaF() * a)))
    return out
