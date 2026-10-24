"""Bramble's icon for Windows: bramble.svg drawn at the sizes Windows asks for, as a .ico."""
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

here = Path(__file__).resolve().parent
svg = here.parent / "bramble" / "ui" / "bramble.svg"
out = here / "bramble.ico"

app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
renderer = QSvgRenderer(str(svg))
image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
renderer.render(painter)
painter.end()
if not image.save(str(out), "ICO"):
    sys.exit(f"could not write {out}")
print(f"wrote {out}")
