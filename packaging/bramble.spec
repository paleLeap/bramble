# PyInstaller recipe for Bramble's downloads (run: pyinstaller packaging/bramble.spec).
#
#   Windows: one file, dist/Bramble.exe, double-clicked to start.
#   Linux:   a folder, dist/Bramble/, with the program Bramble inside.
#
# Carried along: the font, the icon, and the `helpers` / `novaprinter` modules search
# plugins import (as plain files, since plugins find them on sys.path). Not the
# background photos: they stay on the owner's PC, and Bramble draws its plain dark
# background without them.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
pkg = root / "bramble"
windows = sys.platform.startswith("win")

datas = [
    (str(pkg / "ui" / "assets" / "fonts"), "bramble/ui/assets/fonts"),
    (str(pkg / "ui" / "bramble.svg"), "bramble/ui"),
    (str(pkg / "sources" / "_nova"), "bramble/sources/_nova"),
]

# Search sources are found by name at run time, and search plugins (any site's one-file
# .py, loaded when Bramble runs) use parts of Python Bramble itself never imports.
hidden = collect_submodules("bramble") + [
    "PyQt6.QtSvg",
    "html.parser", "html.entities", "http.client", "http.cookiejar", "http.cookies",
    "urllib.request", "urllib.parse", "urllib.error", "json", "gzip", "zlib", "io",
    "tempfile", "base64", "hashlib", "hmac", "ssl", "socket", "datetime", "calendar",
    "concurrent.futures", "xml.etree.ElementTree", "xml.dom.minidom", "email.utils",
    "unicodedata", "codecs", "struct", "random", "string", "math", "itertools",
    "functools", "collections", "textwrap", "difflib", "csv", "uuid",
]

a = Analysis(
    [str(root / "packaging" / "start.py")],
    pathex=[str(root)],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
icon = root / "packaging" / "bramble.ico"

if windows:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Bramble", console=False, upx=False,
              icon=str(icon) if icon.exists() else None)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Bramble", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="Bramble")
