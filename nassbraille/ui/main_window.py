"""Main window: start screen -> reading -> review, with a queue of files."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow, QStackedWidget

from .. import project
from ..convert import SUPPORTED
from . import dev_fake
from .common import APP_NAME, ErrorDialog, add_recent, ar, ask, inform, named, settings
from .reading import ReadingScreen, ReadWorker
from .review_screen import ReviewScreen
from .save_dialog import SaveDialog
from .start_screen import StartScreen
from .style import app_icon

FILE_FILTER = ("ملفات PDF و Word (" + " ".join("*" + ext for ext in SUPPORTED) + ");;"
               "PDF (*.pdf);;Word (*.docx *.doc);;كل الملفات (*)")


def default_reader():
    if dev_fake.enabled():
        return dev_fake.read_document
    from ..convert import read_document
    return read_document


def is_supported(path):
    return Path(path).suffix.lower() in SUPPORTED


class MainWindow(QMainWindow):
    def __init__(self, reader=None):
        super().__init__()
        self.fake = reader is None and dev_fake.enabled()
        self.reader = reader or default_reader()
        self.queue = []
        self.current_path = None
        self._thread = None
        self._worker = None
        self._closing = False
        self._back = None          # (document, reviewed, page index) to return to
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setAcceptDrops(True)
        self.resize(1280, 800)

        self.start = StartScreen(fake=self.fake)
        self.reading = ReadingScreen()
        self.review = ReviewScreen()
        self.stack = QStackedWidget()
        for screen in (self.start, self.reading, self.review):
            self.stack.addWidget(screen)
        self.setCentralWidget(self.stack)
        named(self.start, "شاشة البداية")
        named(self.reading, "شاشة القراية")
        named(self.review, "شاشة المراجعة")

        self.start.openRequested.connect(self.choose_files)
        self.start.filesChosen.connect(self.open_files)
        self.reading.cancelRequested.connect(self.cancel_reading)
        self.review.openRequested.connect(self.choose_files)
        self.review.saveRequested.connect(self.save_files)
        self.review.nextFileRequested.connect(self.next_file)
        self.review.message.connect(self.show_status)

        open_action = QAction("افتح ملف", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        open_action.triggered.connect(self.choose_files)
        self.addAction(open_action)
        self.open_action = open_action

        self.statusBar().setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._restore_geometry()

    # ================================================================ prompts
    # Kept as methods so a test can replace them without real dialogs.
    def ask(self, title, text, yes="أيوه", no="لأ"):
        return ask(self, title, text, yes, no)

    def inform(self, title, text, warning=False):
        inform(self, title, text, warning)

    def show_error(self, message, details=""):
        if details:
            ErrorDialog(self, message, details).exec()
        else:
            inform(self, "مقدرتش أقرا الملف", message, warning=True)

    def show_status(self, text, timeout=6000):
        self.statusBar().showMessage(text, timeout)

    # ================================================================ opening
    def choose_files(self):
        start_dir = str(Path(self.current_path).parent) if self.current_path else ""
        paths, _ = QFileDialog.getOpenFileNames(self, "اختار ملف أو أكتر", start_dir, FILE_FILTER)
        if paths:
            self.open_files(paths)

    def open_files(self, paths):
        """Open the first file now and queue the rest (while reading: queue all)."""
        good, bad = [], []
        for path in paths:
            if not path:
                continue
            path = os.path.normpath(str(path))
            if is_supported(path) and Path(path).is_file():
                if path not in good:
                    good.append(path)
            else:
                bad.append(Path(path).name)
        if bad:
            self.inform("ملفات مش مدعومة",
                        "الملفات دي مش PDF ولا Word، أو مش موجودة:\n" + "\n".join(bad),
                        warning=True)
        if not good:
            return
        if self._thread is not None:
            self.queue.extend(p for p in good if p not in self.queue)
            self.reading.set_waiting(len(self.queue))
            self.show_status(f"اتضاف للقايمة: {ar(len(good))} ملف")
            return
        if self.stack.currentWidget() is self.review and self.review.document:
            self.review.autosave()
            # come back to this review if the new file cannot be read
            self._back = (self.review.document, set(self.review.reviewed), self.review.index)
        self.queue = good[1:] + [p for p in self.queue if p not in good]
        self.open_one(good[0])

    def open_one(self, path):
        self.current_path = path
        add_recent(path)
        self.start.refresh_recent()
        saved = None
        try:
            saved = project.load_project(path)
        except Exception:
            saved = None
        if saved is not None and self.ask("مراجعة قديمة", "فيه مراجعة قديمة للملف ده، تكمل منها؟",
                                          yes="أيوه، كمّل", no="لأ، اقرا الملف من الأول"):
            document, reviewed = saved
            self.show_review(document, reviewed, resumed=True)
            return
        self.start_reading(path)

    def next_file(self):
        if self.stack.currentWidget() is self.review:
            self.review.autosave()
        if self.queue:
            self.open_one(self.queue.pop(0))
        else:
            self.go_home()

    def go_home(self):
        if self.stack.currentWidget() is self.review:
            self.review.autosave()
        self._back = None
        self.review.close_document()
        self.start.refresh_recent()
        self.stack.setCurrentWidget(self.start)
        self.setWindowTitle(APP_NAME)
        self.statusBar().clearMessage()
        self.start.open_btn.setFocus()

    # ================================================================ reading
    def start_reading(self, path):
        self._wait_for_thread()
        self.reading.start(path, len(self.queue))
        self.stack.setCurrentWidget(self.reading)
        self.setWindowTitle(f"{Path(path).name} — {APP_NAME}")
        thread = QThread()
        worker = ReadWorker(path, self.reader)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.reading.set_progress)
        # each handler first stops this thread (queued to the GUI thread)
        worker.done.connect(self._read_done)
        worker.failed.connect(self._read_failed)
        worker.cancelled.connect(self._read_cancelled)
        self._thread, self._worker = thread, worker
        thread.start()
        self.reading.cancel_btn.setFocus()

    def is_reading(self):
        return self._thread is not None

    def cancel_reading(self):
        if self._worker is not None:
            self._worker.cancel()
            self.reading.cancelling()

    def _wait_for_thread(self, timeout=10000):
        thread = self._thread
        if thread is not None:
            thread.quit()
            thread.wait(timeout)
        self._thread = None
        self._worker = None

    def _read_done(self, document):
        self._wait_for_thread()
        if not self._closing:
            self.show_review(document, set())

    def _read_failed(self, message, details):
        self._wait_for_thread()
        if self._closing:
            return
        self.stack.setCurrentWidget(self.start)
        self.show_error(message, details)
        self._after_failure()

    def _read_cancelled(self):
        self._wait_for_thread()
        if self._closing:
            return
        self.show_status("القراية اتوقفت.")
        self._after_failure()

    def _after_failure(self):
        if self.queue:
            self.open_one(self.queue.pop(0))
        elif self._back is not None:
            document, reviewed, index = self._back
            self.show_review(document, reviewed)
            self.review.go_to(index)
        else:
            self.go_home()

    # ================================================================ review
    def show_review(self, document, reviewed, resumed=False):
        if not getattr(document, "pages", None):
            self.stack.setCurrentWidget(self.start)
            self.inform("ملف فاضي", "مفيش ولا صفحة اتقرت من الملف ده.", warning=True)
            self._after_failure()
            return
        self._back = None
        self.review.set_document(document, reviewed, len(self.queue))
        self.stack.setCurrentWidget(self.review)
        self.setWindowTitle(f"{Path(document.source).name} — {APP_NAME}")
        self.review.editor.setFocus()
        if resumed:
            self.show_status(f"كمّلنا من المراجعة القديمة: اتراجع {ar(len(reviewed))} صفحة.")

    def make_save_dialog(self):
        self.review.flush()
        self.review.autosave()
        return SaveDialog(self.review.document, self.review.reviewed, self,
                          has_next=bool(self.queue))

    def save_files(self):
        if not self.review.document:
            return
        dialog = self.make_save_dialog()
        dialog.exec()
        if dialog.next_requested:
            self.next_file()

    # ================================================================ drag and drop
    @staticmethod
    def _dropped_paths(mime):
        if not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def dragEnterEvent(self, event):
        paths = self._dropped_paths(event.mimeData())
        if any(is_supported(p) for p in paths):
            event.acceptProposedAction()
            self.start.set_drag_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if any(is_supported(p) for p in self._dropped_paths(event.mimeData())):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.start.set_drag_active(False)

    def dropEvent(self, event):
        self.start.set_drag_active(False)
        paths = self._dropped_paths(event.mimeData())
        event.acceptProposedAction()
        self.open_files(paths)

    # ================================================================ closing
    def _restore_geometry(self):
        geometry = settings().value("window/geometry")
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except TypeError:
                pass

    def closeEvent(self, event):
        if self.stack.currentWidget() is self.review and self.review.document:
            if not self.review.autosave() and not self.ask(
                    "المراجعة متحفظتش",
                    "مقدرتش أحفظ المراجعة:\n" + (self.review.save_error or "")
                    + "\n\nلو قفلت دلوقتي التعديلات اللي عملتها هتضيع. تقفل برضه؟",
                    yes="اقفل برضه", no="لأ، استنى"):
                event.ignore()
                return
            self.review.save_layout()
            self.review.close_document()
        self._closing = True
        if self._worker is not None:
            self._worker.cancel()
            self._wait_for_thread()
        s = settings()
        s.setValue("window/geometry", self.saveGeometry())
        s.sync()
        event.accept()
