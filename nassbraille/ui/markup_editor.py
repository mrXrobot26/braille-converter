"""The page text editor.

Each editor line (QTextBlock) carries a LineData with the bounding boxes, flags
and confidence of the block it came from, so the line can be found on the page
image and highlighted. Lines the user adds have no LineData. When the page is
left, the lines are parsed back into blocks: an unchanged line gives back its
original block exactly, an edited line is parsed with model.markup_line_to_block
and keeps the boxes/flags/confidence of its source.
"""
from __future__ import annotations

import dataclasses

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPen, QSyntaxHighlighter, QTextBlockUserData, QTextCharFormat,
    QTextCursor, QTextOption,
)
from PySide6.QtWidgets import QPlainTextEdit

from ..model import block_to_markup, markup_line_to_block
from .problems import bad_spans, line_level, spots_in_lines

PICTURE_TEMPLATE = "(صورة: )"
BAD_BG = "#ff9e9e"
LOW_BG = "#ffd59e"
PLACED_BG = "#fff09a"
CURRENT_LINE = QColor(47, 111, 214)


class LineData(QTextBlockUserData):
    """What one editor line knows about the block it was made from."""

    def __init__(self, source=None, bboxes=(), confidence=1.0, flags=()):
        super().__init__()
        self.source = source          # original Block (never changed), None after a join
        self.bboxes = [tuple(b) for b in bboxes]
        self.confidence = 1.0 if confidence is None else float(confidence)
        self.flags = list(flags)

    @classmethod
    def from_block(cls, block):
        return cls(block, block.bboxes, block.confidence, block.flags)

    def copy(self):
        return LineData(self.source, self.bboxes, self.confidence, self.flags)

    @staticmethod
    def joined(a, b):
        """Data for two lines joined into one."""
        if a is None:
            return b.copy() if b is not None else None
        if b is None:
            return a.copy()
        flags = list(dict.fromkeys(list(a.flags) + list(b.flags)))
        bboxes = list(dict.fromkeys(a.bboxes + b.bboxes))
        # two halves of one split line: joined back they may equal the source again
        source = a.source if a.source is b.source else None
        return LineData(source, bboxes, min(a.confidence, b.confidence), flags)


def page_lines(page):
    """[(line, block or None)]: the text of model.page_to_markup(page), line by line."""
    lines, prev_box = [], None
    for block in page.blocks:
        box = block.box_id if block.kind == "box" else None
        if prev_box is not None and box != prev_box:
            lines.append(("", None))
        for part in block_to_markup(block).splitlines() or [""]:
            lines.append((part, block))
        prev_box = box
    if prev_box is not None:
        lines.append(("", None))
    return lines


def _line_text(qblock):
    # Shift+Enter or pasted text can leave Unicode line separators inside a line
    return qblock.text().replace(chr(0x2028), " ").replace(chr(0x2029), " ")


class ProblemHighlighter(QSyntaxHighlighter):
    """Red: characters that cannot be right; orange: unsure line; yellow: placed box."""

    def __init__(self, document):
        super().__init__(document)
        self.bad = QTextCharFormat()
        self.bad.setBackground(QColor(BAD_BG))
        self.bad.setForeground(QColor("#5c0000"))
        self.low = QTextCharFormat()
        self.low.setBackground(QColor(LOW_BG))
        self.placed = QTextCharFormat()
        self.placed.setBackground(QColor(PLACED_BG))

    def highlightBlock(self, text):
        data = self.currentBlockUserData()
        level = line_level(data) if isinstance(data, LineData) else None
        if level == "low":
            self.setFormat(0, len(text), self.low)
        elif level == "placed":
            self.setFormat(0, len(text), self.placed)
        for start, length in bad_spans(text):
            self.setFormat(start, length, self.bad)


class MarkupEditor(QPlainTextEdit):
    currentLineChanged = Signal(object)   # LineData of the cursor line, or None
    userEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editor")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setTabChangesFocus(True)
        option = self.document().defaultTextOption()
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        # QPlainTextEdit uses the alignment as is (no mirroring for RTL)
        option.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
        self.document().setDefaultTextOption(option)
        self.document().setDocumentMargin(8)
        self.highlighter = ProblemHighlighter(self.document())
        self._loading = False
        self._last_line = -1
        self.cursorPositionChanged.connect(self._cursor_moved)
        self.document().contentsChanged.connect(self._contents_changed)

    # ------------------------------------------------------------ loading
    def load_lines(self, lines):
        """lines: [(text, Block or None)] as made by page_lines()."""
        self._loading = True
        try:
            self.setPlainText("\n".join(text for text, _ in lines))
            qblock = self.document().firstBlock()
            for _, block in lines:
                if not qblock.isValid():
                    break
                if block is not None:
                    qblock.setUserData(LineData.from_block(block))
                qblock = qblock.next()
            self.highlighter.rehighlight()
            self.document().setModified(False)
        finally:
            self._loading = False
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self.refresh_current_line()

    def _contents_changed(self):
        if not self._loading and self.document().isModified():
            self.userEdited.emit()

    # ------------------------------------------------------------ reading back
    @staticmethod
    def line_data(qblock):
        data = qblock.userData()
        return data if isinstance(data, LineData) else None

    def current_data(self):
        return self.line_data(self.textCursor().block())

    def to_blocks(self):
        """Parse the lines back into model Blocks (same rules as model.markup_to_blocks)."""
        blocks, box_id, in_box = [], 0, False
        qblock = self.document().firstBlock()
        while qblock.isValid():
            line = _line_text(qblock)
            if not line.strip():
                if in_box:
                    box_id += 1
                in_box = False
            else:
                data = self.line_data(qblock)
                source = data.source if data is not None else None
                if source is not None and block_to_markup(source) == line:
                    block = dataclasses.replace(
                        source, bboxes=list(source.bboxes), flags=list(source.flags),
                        box_id=box_id if source.kind == "box" else None)
                else:
                    block = markup_line_to_block(line, box_id)
                    if data is not None:
                        block.bboxes = list(data.bboxes)
                        block.confidence = data.confidence
                        block.flags = list(data.flags)
                in_box = block.kind == "box"
                blocks.append(block)
            qblock = qblock.next()
        return blocks

    def lines(self):
        """[(text, LineData or None)] for every editor line."""
        out = []
        qblock = self.document().firstBlock()
        while qblock.isValid():
            out.append((qblock.text(), self.line_data(qblock)))
            qblock = qblock.next()
        return out

    def spots(self):
        """[(line number, start, length)] of every F8 stop, in order."""
        return spots_in_lines(self.lines())

    def boxes(self):
        """[((x0, y0, x1, y1), level)] for the image overlay."""
        out = []
        qblock = self.document().firstBlock()
        while qblock.isValid():
            data = self.line_data(qblock)
            if data is not None:
                level = line_level(data)
                out.extend((bbox, level) for bbox in data.bboxes)
            qblock = qblock.next()
        return out

    def line_at_point(self, x, y, slack=2.0):
        """Number of the line whose box contains the point (smallest box wins)."""
        best, best_area = None, None
        qblock = self.document().firstBlock()
        while qblock.isValid():
            data = self.line_data(qblock)
            if data is not None and qblock.text().strip():
                for x0, y0, x1, y1 in data.bboxes:
                    x0, x1 = min(x0, x1), max(x0, x1)
                    y0, y1 = min(y0, y1), max(y0, y1)
                    if x0 - slack <= x <= x1 + slack and y0 - slack <= y <= y1 + slack:
                        area = (x1 - x0) * (y1 - y0)
                        if best_area is None or area < best_area:
                            best, best_area = qblock.blockNumber(), area
            qblock = qblock.next()
        return best

    # ------------------------------------------------------------ moving
    def select_spot(self, line, start=0, length=0):
        qblock = self.document().findBlockByNumber(line)
        if not qblock.isValid():
            return
        cursor = QTextCursor(qblock)
        cursor.setPosition(qblock.position() + min(start, qblock.length() - 1))
        if length:
            end = min(qblock.position() + start + length, qblock.position() + qblock.length() - 1)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _cursor_moved(self):
        number = self.textCursor().blockNumber()
        if number != self._last_line:
            self._last_line = number
            self.viewport().update()
            self.currentLineChanged.emit(self.current_data())

    def refresh_current_line(self):
        self._last_line = -1
        self._cursor_moved()

    def paintEvent(self, event):
        """Outline the cursor line (a background would hide the problem colours)."""
        super().paintEvent(event)
        qblock = self.textCursor().block()
        if not qblock.isValid():
            return
        rect = self.blockBoundingGeometry(qblock).translated(self.contentOffset())
        if rect.bottom() < 0 or rect.top() > self.viewport().height():
            return
        width = self.viewport().width()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(CURRENT_LINE)
        color.setAlpha(150)
        painter.setPen(QPen(color, 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(2.5, rect.top() + 0.5, width - 5, rect.height() - 1), 4, 4)
        bar_x = width - 6 if self.layoutDirection() == Qt.LayoutDirection.RightToLeft else 3
        painter.fillRect(QRectF(bar_x, rect.top() + 2, 3, rect.height() - 4), CURRENT_LINE)
        painter.end()

    # ------------------------------------------------------------ editing
    def insert_picture_line(self):
        """New line «(صورة: )» under the current one, cursor inside the brackets."""
        cursor = self.textCursor()
        cursor.clearSelection()
        cursor.beginEditBlock()
        if self.document().isEmpty():
            cursor.insertText(PICTURE_TEMPLATE)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertBlock()
            cursor.insertText(PICTURE_TEMPLATE)
        cursor.endEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.PreviousCharacter)
        self.setTextCursor(cursor)
        self.setFocus()
        self.ensureCursorVisible()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        plain = mods == Qt.KeyboardModifier.NoModifier
        cursor = self.textCursor()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
                plain or mods == Qt.KeyboardModifier.ShiftModifier):
            self.new_line()   # Shift+Enter too: never a hidden line separator
            return
        if (key == Qt.Key.Key_Backspace and plain and not cursor.hasSelection()
                and cursor.atBlockStart() and cursor.block().previous().isValid()):
            self.join_lines(cursor.block().previous(), cursor.block())
            return
        if (key == Qt.Key.Key_Delete and plain and not cursor.hasSelection()
                and cursor.atBlockEnd() and cursor.block().next().isValid()):
            self.join_lines(cursor.block(), cursor.block().next())
            return
        super().keyPressEvent(event)

    def new_line(self):
        """Split the line at the cursor; both halves keep the link to the image."""
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        data = self.line_data(cursor.block())
        copy = data.copy() if data is not None else None
        cursor.insertBlock()
        cursor.endEditBlock()
        lower = cursor.block()
        if copy is not None and lower.text().strip() and self.line_data(lower) is None:
            lower.setUserData(copy)
            self.highlighter.rehighlightBlock(lower)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.refresh_current_line()

    def join_lines(self, upper, lower):
        """Join `lower` onto the end of `upper`, keeping both lines' image links."""
        a, b = self.line_data(upper), self.line_data(lower)
        if not upper.text().strip():
            data = b.copy() if b is not None else None
        elif not lower.text().strip():
            data = a.copy() if a is not None else None
        else:
            data = LineData.joined(a, b)
        cursor = QTextCursor(lower)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.deletePreviousChar()
        joined = cursor.block()
        joined.setUserData(data)
        self.highlighter.rehighlightBlock(joined)
        self.setTextCursor(cursor)
        self.refresh_current_line()

    # Files dragged from Explorer go to the main window, not into the text
    def canInsertFromMimeData(self, source):
        if source.hasUrls() and any(url.isLocalFile() for url in source.urls()):
            return False
        return super().canInsertFromMimeData(source)
