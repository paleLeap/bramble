"""Visual language for Bramble, taken from Slate (/data/Slate/slate/ui/theme.py).

A dark, low-glare palette with colour reserved for things that carry
information: ready, warning, failed. Everything else is greyscale. The
stylesheet below is Slate's; Bramble's own additions are at the end.
"""

BG          = "#0e1015"
BG_PANEL    = "#151821"
BG_RAISED   = "#1b1f2a"
BG_HOVER    = "#232836"
BORDER      = "#262b38"
TEXT        = "#e4e7ef"
TEXT_DIM    = "#8b93a7"
TEXT_FAINT  = "#5a6175"

UP          = "#31d18a"   # ready / works
DOWN        = "#f0556b"   # failed / missing
FLAT        = "#7d8598"
ACCENT      = "#5b8dff"
WARN        = "#f5a94b"
HOT         = "#c77dff"
SELECT      = "#203558"
ZEBRA       = "#1b1f2b"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Inter', 'DejaVu Sans', sans-serif;
    font-size: 12px;
}}
QMainWindow, QDialog {{ background: {BG}; }}

QFrame#panel {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#panelFlat {{ background: transparent; border: none; }}

/* -- the panel canvas -------------------------------------------------- */
QWidget#canvas {{ background: {BG}; }}
QFrame#panelFrame {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QPushButton#panelClose {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 0px 6px;
    color: {TEXT_FAINT};
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#panelClose:hover {{ background: {BG_HOVER}; color: {DOWN}; }}
QPushButton#ghost {{
    background: transparent;
    border: 1px solid {BORDER};
    color: {TEXT_DIM};
    font-size: 14px;
    font-weight: 700;
    padding: 4px 12px;
}}
QPushButton#ghost:hover {{
    background: {BG_RAISED}; color: {TEXT}; border-color: {ACCENT};
}}

QMenu {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px;
}}
QMenu::item {{ padding: 5px 24px 5px 12px; border-radius: 4px; color: {TEXT}; }}
QMenu::item:selected {{ background: {BG_HOVER}; }}
QMenu::item:disabled {{ color: {TEXT_FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QLabel#panelTitle {{
    color: {TEXT_DIM};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
    padding: 2px 0px;
}}
QLabel#brand {{
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 5px;
    color: {TEXT};
}}
QLabel#chip {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 3px 10px;
    color: {TEXT_DIM};
    font-size: 11px;
}}
QLabel#bigTicker {{ font-size: 26px; font-weight: 800; letter-spacing: 1px; }}
QLabel#bigScore  {{ font-size: 26px; font-weight: 800; }}
QLabel#dim       {{ color: {TEXT_DIM}; }}
QLabel#faint     {{ color: {TEXT_FAINT}; font-size: 11px; }}

QAbstractScrollArea {{ background: {BG_PANEL}; }}
QAbstractScrollArea > QWidget > QWidget {{ background: {BG_PANEL}; }}
QTableView, QTableWidget {{
    background: {BG_PANEL};
    alternate-background-color: {ZEBRA};
    gridline-color: {BORDER};
    border: none;
    selection-background-color: {SELECT};
    selection-color: {TEXT};
    font-size: 12px;
}}
QHeaderView::section {{
    background: {BG};
    color: {TEXT_FAINT};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 6px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
}}
QTableWidget::item {{ padding: 4px 6px; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: {BG_PANEL}; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_FAINT};
    padding: 4px 12px;
    margin-right: 1px;
    border-bottom: 2px solid transparent;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT_DIM}; }}

QPushButton {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    color: {TEXT};
    font-size: 11px;
    font-weight: 600;
}}
QPushButton:hover  {{ background: {BG_HOVER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #08101f; }}
QPushButton#primary:hover {{ background: #6f9bff; }}

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
/* Drop-down lists: a plain dark list under the box. The default popup
   style drew light scroller strips above and below the items. */
QComboBox {{ combobox-popup: 0; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 3px;
    outline: 0;
    selection-background-color: {SELECT};
    selection-color: {TEXT};
}}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 0px 10px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSlider::groove:horizontal {{
    height: 4px; background: {BORDER}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 13px; margin: -5px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 30px; }}

QSplitter::handle {{ background: {BG}; }}
QSplitter::handle:horizontal {{ width: 6px; }}
QSplitter::handle:vertical {{ height: 6px; }}

QToolTip {{
    background: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
    border-radius: 4px;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 10px;
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
"""

BRAMBLE_EXTRA = f"""
QFrame#panel QLabel, QFrame#panel QCheckBox, QFrame#panel QRadioButton,
QFrame#panelFlat QLabel, QDialog QLabel, QDialog QRadioButton, QDialog QCheckBox,
QFrame#issue QLabel, QFrame#issueBad QLabel, QFrame#issueInfo QLabel {{ background: transparent; }}
QWidget#issueHolder {{ background: {BG_PANEL}; }}
QListWidget, QTreeWidget {{
    background: {BG_PANEL};
    border: none;
    outline: 0;
    font-size: 12px;
}}
QListWidget::item, QTreeWidget::item {{ padding: 6px 8px; border-radius: 5px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {BG_HOVER}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{ background: {SELECT}; color: {TEXT}; }}
QTreeView::branch {{ background: {BG_PANEL}; }}
QWidget#headerBar {{ background: {BG_PANEL}; border-bottom: 1px solid {BORDER}; }}
QLabel#headerBrand {{
    color: {TEXT_FAINT}; font-size: 15px; font-weight: 800; letter-spacing: 4px;
    background: transparent;
}}
QPushButton#pageTab {{
    background: transparent; border: none; border-bottom: 2px solid transparent;
    border-radius: 0px; color: {TEXT_FAINT}; padding: 6px 10px;
    font-size: 11px; font-weight: 700; letter-spacing: 1.5px;
}}
QPushButton#pageTab:hover {{ color: {TEXT_DIM}; }}
QPushButton#pageTab:checked {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QPushButton#primary:disabled {{ background: {BG_RAISED}; border-color: {BORDER}; color: {TEXT_FAINT}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; }}
QLabel#title    {{ font-size: 20px; font-weight: 800; }}
QLabel#subtitle {{ color: {TEXT_DIM}; font-size: 12px; }}
QLabel#body     {{ color: {TEXT}; font-size: 12px; }}
QLabel#ok       {{ color: {UP}; }}
QLabel#warn     {{ color: {WARN}; }}
QLabel#bad      {{ color: {DOWN}; }}
QFrame#issue {{
    background: {BG_RAISED}; border: 1px solid {BORDER};
    border-left: 3px solid {WARN}; border-radius: 6px;
}}
QFrame#issueBad {{
    background: {BG_RAISED}; border: 1px solid {BORDER};
    border-left: 3px solid {DOWN}; border-radius: 6px;
}}
QFrame#issueInfo {{
    background: {BG_RAISED}; border: 1px solid {BORDER};
    border-left: 3px solid {ACCENT}; border-radius: 6px;
}}
QWidget#statusBar {{ background: {BG_PANEL}; border-top: 1px solid {BORDER}; }}
QLabel#status {{ color: {TEXT_DIM}; font-size: 11px; background: transparent; }}
QTextBrowser {{ background: {BG_PANEL}; border: none; color: {TEXT}; font-size: 12px; }}
QProgressBar {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 4px;
    height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""

STYLESHEET = STYLESHEET + BRAMBLE_EXTRA
