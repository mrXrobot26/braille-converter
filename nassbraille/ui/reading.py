"""Reading a file in a worker thread, and the screen shown meanwhile."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..convert import ConversionError
from .common import ar, named, rtl

UNEXPECTED = ("حصلت مشكلة مش متوقعة وإحنا بنقرا الملف ده. جرّب تفتحه تاني، "
              "ولو المشكلة فضلت ابعت التفاصيل للي عامل البرنامج.")
MISSING_PART = ("جزء من البرنامج ناقص أو لسه مخلصش، فمقدرتش أقرا الملف ده. "
                "ابعت التفاصيل للي عامل البرنامج.")


class ReadCancelled(BaseException):
    """Raised from the progress callback to stop a reader (not an Exception,
    so a reader's own `except Exception` cannot swallow it)."""


class ReadWorker(QObject):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str, str)      # friendly message, technical details
    cancelled = Signal()

    def __init__(self, path, reader):
        super().__init__()
        self.path = str(path)
        self.reader = reader
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _progress(self, done=0, total=0, message="", *args, **kwargs):
        if self._cancel:
            raise ReadCancelled()
        try:
            self.progress.emit(int(done or 0), int(total or 0), str(message or ""))
        except (TypeError, ValueError):
            pass

    @Slot()
    def run(self):
        try:
            document = self.reader(self.path, progress=self._progress)
        except ReadCancelled:
            self.cancelled.emit()
            return
        except ConversionError as exc:
            self.failed.emit(str(exc) or "مقدرتش أقرا الملف ده.", "")
            return
        except ImportError:
            self.failed.emit(MISSING_PART, traceback.format_exc())
            return
        except Exception:
            self.failed.emit(UNEXPECTED, traceback.format_exc())
            return
        if self._cancel:
            self.cancelled.emit()
        else:
            self.done.emit(document)


class ReadingScreen(QWidget):
    cancelRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(520)
        card.setMaximumWidth(700)
        row.addWidget(card, 3)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(12)
        self.title = QLabel("بقرا الملف…")
        self.title.setObjectName("pageTitle")
        named(self.title, "بقرا الملف")
        self.file_label = QLabel()
        self.file_label.setWordWrap(True)
        named(self.file_label, "اسم الملف")
        self.queue_label = QLabel()
        self.queue_label.setObjectName("muted")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        named(self.bar, "تقدم القراية")
        self.message = QLabel()
        self.message.setObjectName("muted")
        named(self.message, "حالة القراية")
        self.hint = QLabel("الملفات الصعبة بتاخد وقت. بعد ما القراية تخلص هتراجع كل صفحة قصاد صورتها.")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        self.cancel_btn = QPushButton("وقّف القراية")
        self.cancel_btn.clicked.connect(self.cancelRequested)
        named(self.cancel_btn, "وقف القراية")
        layout.addWidget(self.title)
        layout.addWidget(self.file_label)
        layout.addWidget(self.queue_label)
        layout.addWidget(self.bar)
        layout.addWidget(self.message)
        layout.addWidget(self.hint)
        layout.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignLeft)

    def start(self, path, waiting=0):
        self.title.setText("بقرا الملف…")
        self.file_label.setText(rtl(Path(path).name))
        self.file_label.setToolTip(str(path))
        self.set_waiting(waiting)
        self.bar.setRange(0, 0)       # busy until the reader says how much
        self.message.setText("بجهّز…")
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("وقّف القراية")

    def set_waiting(self, waiting):
        self.queue_label.setText(f"وبعده مستني {ar(waiting)} ملف" if waiting else "")
        self.queue_label.setVisible(bool(waiting))

    @Slot(int, int, str)
    def set_progress(self, done, total, message):
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(max(0, min(done, total)))
        else:
            self.bar.setRange(0, 0)
        self.message.setText(message or (f"صفحة {ar(done)} من {ar(total)}" if total else ""))

    def cancelling(self):
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("بوقّف…")
