"""The page image (rendered with PyMuPDF) with the block rectangles on top."""
from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene

try:
    import pymupdf
except ImportError:  # pragma: no cover - older PyMuPDF
    import fitz as pymupdf

DPI = 110
ZOOM_STEP = 1.25
MIN_ZOOM, MAX_ZOOM = 0.15, 6.0


def _pen(color, width):
    pen = QPen(color, width)
    pen.setCosmetic(True)   # same thickness at every zoom
    return pen


STYLES = {
    None: (_pen(QColor(47, 111, 214, 105), 1.0), QBrush(Qt.BrushStyle.NoBrush)),
    "low": (_pen(QColor(226, 132, 0, 210), 1.5), QBrush(QColor(255, 165, 40, 38))),
    "placed": (_pen(QColor(196, 158, 0, 220), 1.5), QBrush(QColor(255, 220, 40, 45))),
}
CURRENT = (_pen(QColor(20, 88, 214, 240), 2.5), QBrush(QColor(47, 111, 214, 60)))


class PdfRenderer:
    """Renders pages of one PDF at about 110 DPI and keeps the last few."""

    def __init__(self, path, dpi=DPI, keep=8):
        self.path = str(path)
        self.dpi = dpi
        self.keep = keep
        self._pdf = None
        self._cache = OrderedDict()

    def render(self, number):
        """(QImage, (width, height) in points) for the 1-based page number."""
        if number in self._cache:
            self._cache.move_to_end(number)
            return self._cache[number]
        if self._pdf is None:
            self._pdf = pymupdf.open(self.path)
        if not 1 <= number <= self._pdf.page_count:
            raise IndexError(f"page {number} not in PDF ({self._pdf.page_count} pages)")
        page = self._pdf[number - 1]
        zoom = self.dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride,
                       QImage.Format.Format_RGB888).copy()
        result = (image, (page.rect.width, page.rect.height))
        self._cache[number] = result
        while len(self._cache) > self.keep:
            self._cache.popitem(last=False)
        return result

    def close(self):
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None
        self._cache.clear()


class PageView(QGraphicsView):
    pointClicked = Signal(float, float)   # page points
    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setBackgroundBrush(QColor("#e4e7eb"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pixmap = None
        self._boxes = []
        self._marks = []
        self._px_per_pt = (1.0, 1.0)
        self.zoom = 1.0
        self.fit_mode = True
        self._press = None

    # ------------------------------------------------------------ content
    def clear_page(self):
        self.scene().clear()
        self._pixmap = None
        self._boxes = []
        self._marks = []

    def has_page(self):
        return self._pixmap is not None

    def set_page(self, image, size_pt, boxes=()):
        """image: QImage; size_pt: page size in points; boxes: [(bbox, level)]."""
        self.clear_page()
        pixmap = QPixmap.fromImage(image)
        self._pixmap = self.scene().addPixmap(pixmap)
        self._pixmap.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        width, height = size_pt or (pixmap.width(), pixmap.height())
        self._px_per_pt = (pixmap.width() / width, pixmap.height() / height)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        for bbox, level in boxes:
            pen, brush = STYLES.get(level, STYLES[None])
            item = self.scene().addRect(self.to_pixels(bbox), pen, brush)
            item.setZValue(1)
            self._boxes.append(item)
        if self.fit_mode:
            self.fit_width()
        else:
            self._apply_zoom()

    def to_pixels(self, bbox):
        sx, sy = self._px_per_pt
        x0, y0, x1, y1 = bbox
        return QRectF(QPointF(min(x0, x1) * sx, min(y0, y1) * sy),
                      QPointF(max(x0, x1) * sx, max(y0, y1) * sy))

    def box_count(self):
        return len(self._boxes)

    def marked_rects(self):
        return [item.rect() for item in self._marks]

    def highlight(self, bboxes, scroll=True):
        """Show the current line's rectangles strongly and scroll them into view."""
        for item in self._marks:
            self.scene().removeItem(item)
        self._marks = []
        if self._pixmap is None:
            return
        pen, brush = CURRENT
        union = QRectF()
        for bbox in bboxes:
            rect = self.to_pixels(bbox)
            item = self.scene().addRect(rect, pen, brush)
            item.setZValue(2)
            self._marks.append(item)
            union = union.united(rect)
        if scroll and self._marks:
            target = union
            visible = self.mapToScene(self.viewport().rect()).boundingRect()
            if union.height() > visible.height() * 0.9:
                target = self._marks[0].rect()
            self.ensureVisible(target, 30, 50)

    # ------------------------------------------------------------ zoom
    def _apply_zoom(self):
        self.setTransform(QTransform.fromScale(self.zoom, self.zoom))
        self.zoomChanged.emit(self.zoom)

    def set_zoom(self, zoom):
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self._apply_zoom()

    def zoom_in(self):
        self.fit_mode = False
        self.set_zoom(self.zoom * ZOOM_STEP)

    def zoom_out(self):
        self.fit_mode = False
        self.set_zoom(self.zoom / ZOOM_STEP)

    def fit_width(self):
        self.fit_mode = True
        if self._pixmap is None:
            return
        width = self._pixmap.pixmap().width()
        available = self.viewport().width() - 6
        if width > 0 and available > 40:
            self.set_zoom(available / width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit_width()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            elif event.angleDelta().y() < 0:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif event.key() == Qt.Key.Key_Minus:
            self.zoom_out()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------ clicks
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        moved = (event.position() - self._press).manhattanLength()
        self._press = None
        if moved > 5 or self._pixmap is None:
            return   # that was a drag to scroll
        point = self.mapToScene(event.position().toPoint())
        if self.sceneRect().contains(point):
            sx, sy = self._px_per_pt
            self.pointClicked.emit(point.x() / sx, point.y() / sy)
