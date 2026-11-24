"""애플(파이널컷) 느낌의 다크 테마."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#0a84ff"

QSS = f"""
QWidget {{ color: #f2f2f7; font-size: 13px; }}
QMainWindow, QWidget#viewer {{ background: #0b0b0c; }}
QWidget#panel, QScrollArea#panel {{ background: #1e1e20; border: none; }}
QToolBar {{ background: #2c2c2e; border: none; border-bottom: 1px solid #000; padding: 5px 10px; spacing: 4px; }}
QToolBar QToolButton {{ border-radius: 6px; padding: 5px 11px; color: #f2f2f7; }}
QToolBar QToolButton:hover {{ background: #3a3a3c; }}
QToolBar QToolButton:checked {{ background: {ACCENT}; color: white; }}
QToolBar QToolButton:disabled {{ color: #5a5a5e; }}
QToolButton#play {{ background: #2c2c2e; border-radius: 18px; font-size: 15px; }}
QToolButton#play:hover {{ background: #3a3a3c; }}
QToolButton#preset {{ background: #2c2c2e; border: 1px solid transparent; border-radius: 9px; padding: 4px;
                      font-size: 11px; color: #d1d1d6; }}
QToolButton#preset:hover {{ background: #3a3a3c; }}
QToolButton#preset:checked {{ background: rgba(10, 132, 255, 0.22); border: 1px solid {ACCENT}; color: white; }}
QPushButton {{ background: #3a3a3c; border: none; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ background: #48484a; }}
QPushButton:pressed {{ background: #545458; }}
QPushButton:disabled {{ background: #2c2c2e; color: #5a5a5e; }}
QPushButton#danger {{ color: #ff453a; }}
QLineEdit, QSpinBox, QComboBox {{ background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 6px;
                                  padding: 4px 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: #2c2c2e; border: 1px solid #3a3a3c; selection-background-color: {ACCENT}; }}
QLabel#title {{ font-size: 17px; font-weight: 600; }}
QLabel#section {{ color: #8e8e93; font-size: 11px; font-weight: 600; padding-top: 10px; }}
QLabel#muted {{ color: #8e8e93; }}
QLabel#timecode {{ font-family: Menlo, monospace; font-size: 15px; color: #f2f2f7; }}
QFrame#line {{ background: #2c2c2e; max-height: 1px; border: none; }}
QSplitter::handle {{ background: #000; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QTableWidget {{ background: #2c2c2e; border: none; border-radius: 8px; gridline-color: transparent;
                selection-background-color: {ACCENT}; }}
QHeaderView::section {{ background: #2c2c2e; color: #8e8e93; border: none; padding: 4px 6px; font-size: 11px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #48484a; border-radius: 4px; min-height: 24px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{ background: #2c2c2e; border: 1px solid #3a3a3c; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px 6px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::item:disabled {{ color: #8e8e93; }}
QMenu::separator {{ height: 1px; background: #3a3a3c; margin: 4px 6px; }}
QStatusBar {{ background: #2c2c2e; color: #8e8e93; border-top: 1px solid #000; }}
QStatusBar QLabel {{ color: #aeaeb2; font-size: 12px; }}
QProgressBar {{ background: #1c1c1e; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QToolTip {{ background: #3a3a3c; color: #f2f2f7; border: none; padding: 4px 6px; }}
"""


def apply_theme(app: QApplication):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [(QPalette.ColorRole.Window, "#1e1e20"), (QPalette.ColorRole.WindowText, "#f2f2f7"),
                        (QPalette.ColorRole.Base, "#2c2c2e"), (QPalette.ColorRole.AlternateBase, "#323234"),
                        (QPalette.ColorRole.Text, "#f2f2f7"), (QPalette.ColorRole.Button, "#3a3a3c"),
                        (QPalette.ColorRole.ButtonText, "#f2f2f7"), (QPalette.ColorRole.Highlight, ACCENT),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, "#3a3a3c"),
                        (QPalette.ColorRole.ToolTipText, "#f2f2f7"), (QPalette.ColorRole.PlaceholderText, "#636366")]:
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#5a5a5e"))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
