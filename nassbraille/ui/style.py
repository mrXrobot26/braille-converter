"""Look of the program: light Fusion style, Arabic-friendly fonts, drawn icons."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF,
)

UI_FONT = "Segoe UI"
UI_SIZE = 11
EDITOR_SIZE = 12

ACCENT = "#2f6fd6"
OK_GREEN = "#2e9d5b"
WARN_ORANGE = "#e8920c"

STYLESHEET = f"""
QMainWindow, QDialog {{ background: #f5f6f8; }}
QPushButton {{
    padding: 6px 14px; border: 1px solid #c4cad3; border-radius: 6px; background: #ffffff;
    min-height: 22px;
}}
QPushButton:hover {{ background: #eef3fb; border-color: #9db5dd; }}
QPushButton:pressed {{ background: #dfe8f7; }}
QPushButton:focus {{ border: 2px solid {ACCENT}; }}
QPushButton:disabled {{ color: #9aa1ab; background: #f1f2f4; border-color: #dcdfe4; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: 1px solid #2a63c0; font-weight: 600; }}
QPushButton#primary:hover {{ background: #2a63c0; }}
QPushButton#primary:focus {{ border: 2px solid #163a75; }}
QPushButton#primary:disabled {{ background: #a9bfe6; border-color: #a9bfe6; color: #f4f7fc; }}
QPushButton#done {{ background: {OK_GREEN}; color: white; border: 1px solid #25804a; font-weight: 600; }}
QPushButton#done:hover {{ background: #25804a; }}
QPushButton#done:focus {{ border: 2px solid #14512d; }}
QPushButton#big {{ font-size: 17pt; padding: 14px 48px; border-radius: 10px; background: {ACCENT};
                  color: white; border: 1px solid #2a63c0; font-weight: 600; }}
QPushButton#big:hover {{ background: #2a63c0; }}
QPushButton#big:focus {{ border: 3px solid #163a75; }}
QPushButton#flat {{ border: none; background: transparent; color: {ACCENT}; padding: 2px 6px; }}
QPushButton#flat:hover {{ text-decoration: underline; }}
QPushButton#flat:focus {{ border: 1px solid {ACCENT}; }}
QFrame#card {{ background: #ffffff; border: 1px solid #dde1e7; border-radius: 10px; }}
QFrame#header {{ background: #ffffff; border-bottom: 1px solid #dde1e7; }}
QFrame#actionBar {{ background: #ffffff; border-top: 1px solid #dde1e7; }}
QFrame#banner {{ background: #fff4d9; border: 1px solid #efc56b; border-radius: 6px; }}
QFrame#bannerInfo {{ background: #eaf2ff; border: 1px solid #b6cdf2; border-radius: 6px; }}
QFrame#dropZone {{ background: #fbfcfe; border: 2px dashed #a9bad3; border-radius: 12px; }}
QFrame#dropZone[active="true"] {{ background: #eaf2ff; border-color: {ACCENT}; }}
QLabel#title {{ font-size: 22pt; font-weight: 700; color: #1f2d3d; }}
QLabel#subtitle {{ font-size: 12pt; color: #4a5568; }}
QLabel#pageTitle {{ font-size: 13pt; font-weight: 700; color: #1f2d3d; }}
QLabel#muted {{ color: #66707c; }}
QLabel#legend {{ color: #4a5568; }}
QLabel#chipDone {{ background: #e3f4ea; color: #1f6b3f; border: 1px solid #a8d8bb; border-radius: 10px; }}
QLabel#chipTodo {{ background: #ffffff; color: #4a5568; border: 1px solid #d0d5dc; border-radius: 10px; }}
QLabel#errorMessage {{ font-size: 11.5pt; }}
QLabel#warnText {{ color: #8a4b00; }}
QLabel#resultTitle {{ font-size: 15pt; font-weight: 700; color: #1f6b3f; }}
QPlainTextEdit#editor {{
    background: #ffffff; border: 1px solid #c4cad3; border-radius: 6px; padding: 4px;
    selection-background-color: #9cc0f5; selection-color: #000000;
}}
QPlainTextEdit#editor:focus {{ border: 2px solid {ACCENT}; }}
QListWidget {{ background: #ffffff; border: 1px solid #dde1e7; border-radius: 6px; padding: 2px; }}
QListWidget::item {{ padding: 5px 4px; border-radius: 4px; }}
QListWidget::item:selected {{ background: #dbe7fb; color: #10213a; }}
QListWidget::item:hover {{ background: #eef3fb; }}
QListWidget:focus {{ border: 2px solid {ACCENT}; }}
QGroupBox {{ font-weight: 600; border: 1px solid #dde1e7; border-radius: 8px; margin-top: 14px;
            padding: 10px 8px 8px 8px; background: #ffffff; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; }}
QProgressBar {{ border: 1px solid #c4cad3; border-radius: 6px; background: #ffffff; height: 20px;
               text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QGraphicsView {{ background: #e4e7eb; border: 1px solid #c4cad3; border-radius: 6px; }}
QToolTip {{ background: #ffffe8; color: #000000; border: 1px solid #c4cad3; }}
QStatusBar {{ background: #ffffff; border-top: 1px solid #dde1e7; }}
"""


def light_palette():
    pal = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f5f6f8",
        QPalette.ColorRole.WindowText: "#1f2d3d",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f3f5f8",
        QPalette.ColorRole.Text: "#111111",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#1f2d3d",
        QPalette.ColorRole.Highlight: "#9cc0f5",
        QPalette.ColorRole.HighlightedText: "#000000",
        QPalette.ColorRole.ToolTipBase: "#ffffe8",
        QPalette.ColorRole.ToolTipText: "#000000",
        QPalette.ColorRole.PlaceholderText: "#8a929c",
        QPalette.ColorRole.Link: ACCENT,
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#e9ecf0",
        QPalette.ColorRole.Mid: "#c4cad3",
        QPalette.ColorRole.Dark: "#9aa1ab",
        QPalette.ColorRole.Shadow: "#6b7280",
    }
    for role, color in colors.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor("#9aa1ab"))
    return pal


def apply_style(app):
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:  # older Qt
        pass
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    # Arabic text plus a fallback for the few symbols (check mark) we show
    QFont.insertSubstitutions(UI_FONT, ["Segoe UI Symbol", "Arial", "Tahoma"])
    font = QFont(UI_FONT, UI_SIZE)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)


def editor_font():
    return QFont(UI_FONT, EDITOR_SIZE)


# --------------------------------------------------------------- icons

def _pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _check_path(size):
    path = QPainterPath()
    path.moveTo(size * 0.28, size * 0.52)
    path.lineTo(size * 0.44, size * 0.68)
    path.lineTo(size * 0.73, size * 0.36)
    return path


@lru_cache(maxsize=None)
def status_pixmap(kind, size=32):
    """kind: 'done' (green check), 'warn' (orange triangle), 'none' (grey ring)."""
    pm = _pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if kind == "done":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(OK_GREEN))
        p.drawEllipse(QRectF(2, 2, size - 4, size - 4))
        pen = QPen(QColor("white"), size * 0.11, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(_check_path(size))
    elif kind == "warn":
        p.setPen(QPen(QColor("#c77700"), 1.2))
        p.setBrush(QColor(WARN_ORANGE))
        tri = QPolygonF([QPointF(size / 2, 2.5), QPointF(size - 2.5, size - 4),
                         QPointF(2.5, size - 4)])
        p.drawPolygon(tri)
        p.setPen(QPen(QColor("white"), size * 0.1, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(size / 2, size * 0.36), QPointF(size / 2, size * 0.6))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        r = size * 0.06
        p.drawEllipse(QPointF(size / 2, size * 0.73), r, r)
    else:
        p.setPen(QPen(QColor("#b5bcc6"), size * 0.08))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6))
    p.end()
    return pm


@lru_cache(maxsize=None)
def status_icon(kind):
    return QIcon(status_pixmap(kind, 32))


@lru_cache(maxsize=None)
def app_icon():
    """Six braille dots on a blue tile."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = _pixmap(size)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.2, size * 0.2)
        p.setBrush(QColor("white"))
        r = size * 0.085
        for col, x in enumerate((0.36, 0.64)):
            for row, y in enumerate((0.27, 0.5, 0.73)):
                filled = (col, row) in {(0, 0), (1, 0), (0, 1), (1, 2), (0, 2)}
                if filled:
                    p.setBrush(QColor("white"))
                    p.setPen(Qt.PenStyle.NoPen)
                else:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor("white"), max(1.0, size * 0.03)))
                p.drawEllipse(QPointF(size * x, size * y), r, r)
        p.end()
        icon.addPixmap(pm)
    return icon
