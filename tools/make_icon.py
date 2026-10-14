"""Draw the program icon (a braille cell) into assets/icon.ico and icon.png."""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter, QPen

ROOT = Path(__file__).resolve().parent.parent


def draw(size):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    m = size * 0.06
    p.setBrush(QBrush(QColor("#1F4E79")))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.18, size * 0.18)
    # braille cell: dots 1,2,4,5 raised (the letter "g"), dots 3,6 shown faint
    r = size * 0.085
    cols = (size * 0.36, size * 0.64)
    rows = (size * 0.27, size * 0.5, size * 0.73)
    raised = {(0, 0), (0, 1), (1, 0), (1, 1)}
    for ci, x in enumerate(cols):
        for ri, y in enumerate(rows):
            if (ci, ri) in raised:
                p.setBrush(QBrush(QColor("#FFFFFF")))
                p.setPen(Qt.NoPen)
            else:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 110), size * 0.02))
            p.drawEllipse(QRectF(x - r, y - r, 2 * r, 2 * r))
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    draw(256).save(str(out / "icon.png"))
    ok = draw(256).save(str(out / "icon.ico"))
    print("icon.ico written:", ok)
