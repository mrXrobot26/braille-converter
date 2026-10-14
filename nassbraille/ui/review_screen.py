"""Review screen: compare every page's image with its text and fix the text."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSplitter,
    QSizePolicy, QStackedWidget, QStyle, QTextBrowser, QVBoxLayout, QWidget,
)

from .. import project
from .common import ar, ar_list, named, settings
from .markup_editor import BAD_BG, LOW_BG, PLACED_BG, MarkupEditor, page_lines
from .page_view import PageView, PdfRenderer
from .problems import page_has_text, page_needs_attention, spots_in_lines
from .style import status_icon, status_pixmap

AUTOSAVE_MS = 2000
LRI, PDI = chr(0x2066), chr(0x2069)   # keep Latin key names in one piece in Arabic text

STATUS_TEXT = {"done": "اتراجعت", "warn": "فيها حاجات محتاجة مراجعة", "none": "لسه"}

REPORT_LABELS = {
    "pages": "عدد الصفحات",
    "page_count": "عدد الصفحات",
    "image_only_pages": "صفحات صورة بس (من غير كلام مكتوب)",
    "image_pages": "صفحات صورة بس (من غير كلام مكتوب)",
    "scanned_pages": "صفحات متصورة بالسكانر",
    "ocr_pages": "صفحات اتقرت من الصورة",
    "pages_with_warnings": "صفحات فيها تنبيهات",
    "warning_pages": "صفحات فيها تنبيهات",
    "low_confidence_blocks": "سطور البرنامج مش متأكد منها",
    "low_confidence": "سطور البرنامج مش متأكد منها",
    "odd_chars": "حروف غريبة",
    "unknown_chars": "حروف مش معروفة",
    "unknown_glyphs": "حروف مش معروفة",
    "broken_fonts": "خطوط بايظة",
    "fonts": "الخطوط",
    "reader": "طريقة القراية",
    "method": "طريقة القراية",
    "methods": "الصفحات اتقرت إزاي",
    "seconds": "وقت القراية (ثانية)",
    "elapsed": "وقت القراية (ثانية)",
    # PDF reader
    "headings_by_style": "عناوين اتعرفت من شكل الخط",
    "tagged": "الملف فيه ترتيب للكلام متسجل جواه",
    "numerals": "الأرقام في الملف",
    # Word reader
    "blocks": "عدد الفقرات",
    "pictures": "صور",
    "text_boxes": "مربعات كلام",
    "tables": "جداول",
    "footnotes": "هوامش تحت الصفحة",
    "endnotes": "هوامش آخر الملف",
    "charts": "رسومات بيانية",
    "smartart": "أشكال SmartArt",
    "equations": "معادلات",
    "symbols_dropped": "رموز اتشالت",
    "hidden_runs": "كلام مخفي اتشال",
}
VALUE_WORDS = {
    "tagged": "من الترتيب المتسجل في الملف",
    "geometric": "من أماكن الكلام في الصفحة",
    "ocr": "من صورة الصفحة",
    "arabic": "١٢٣",
    "western": "123",
    "mixed": "مخلوط",
    "docx": "Word",
    "pdf": "PDF",
}
IMAGE_ONLY_KEYS = ("image_only_pages", "image_pages", "scanned_pages")


def keys_hint(text):
    return LRI + text + PDI


def format_value(value):
    """A report value in plain words, whatever its type."""
    if isinstance(value, bool):
        return "أيوه" if value else "لأ"
    if isinstance(value, (int, float)):
        return ar(round(value, 2) if isinstance(value, float) else value)
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        if not items:
            return "مفيش"
        if all(isinstance(v, int) and not isinstance(v, bool) for v in items):
            return f"{ar_list(items)}  (العدد: {ar(len(items))})"
        shown = "، ".join(str(VALUE_WORDS.get(v, v) if isinstance(v, str) else v)
                          for v in items[:20])
        return shown + ("، …" if len(items) > 20 else "")
    if isinstance(value, dict):
        if not value:
            return "مفيش"
        if all(isinstance(v, dict) for v in value.values()):   # e.g. per-font details
            names = [str(k) for k in value][:12]
            more = "، …" if len(value) > 12 else ""
            return "، ".join(names) + more + f"  (العدد: {ar(len(value))})"
        return "؛ ".join(f"{VALUE_WORDS.get(k, k)}: {format_value(v)}" for k, v in value.items())
    if isinstance(value, str):
        return VALUE_WORDS.get(value, value)
    return str(value)


def count_of(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return None


class ReportDialog(QDialog):
    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تقرير القراية")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        view = QTextBrowser()
        named(view, "تقرير القراية")
        rows = [("الملف", Path(document.source).name),
                ("نوع الملف", "PDF" if document.kind == "pdf" else "Word")]
        report = document.report if isinstance(document.report, dict) else {}
        for key, value in report.items():
            rows.append((REPORT_LABELS.get(str(key), str(key)), format_value(value)))
        html = ["<table dir='rtl' cellspacing='0' cellpadding='6' width='100%'>"]
        for label, value in rows:
            html.append(f"<tr><td style='color:#4a5568'><b>{_esc(label)}</b></td>"
                        f"<td>{_esc(value)}</td></tr>")
        html.append("</table>")
        view.setHtml("".join(html))
        layout.addWidget(view)
        ok = QPushButton("تمام")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        named(ok, "تمام")
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(ok)
        layout.addLayout(row)


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class ReviewScreen(QWidget):
    saveRequested = Signal()
    openRequested = Signal()
    nextFileRequested = Signal()
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = None
        self.reviewed = set()
        self.index = -1
        self.renderer = None
        self.dirty = False
        self.save_error = None
        self.saver = project.save_project      # replaceable in tests
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_MS)
        self._timer.timeout.connect(self.autosave)
        self._build()
        self._make_actions()
        self._restore_splitter()

    # ================================================================ layout
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(self._build_pages())
        self.splitter.addWidget(self._build_text())
        self.splitter.addWidget(self._build_image())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([150, 560, 560])
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 8)
        body_layout.addWidget(self.splitter)
        root.addWidget(body, 1)
        root.addWidget(self._build_actions())

    def _build_header(self):
        header = QFrame()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)
        self.file_label = QLabel()
        self.file_label.setObjectName("pageTitle")
        named(self.file_label, "اسم الملف")
        self.report_label = QLabel()
        self.report_label.setObjectName("muted")
        self.report_label.setMinimumWidth(40)    # may be cut on a small screen, never widens it
        self.report_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        named(self.report_label, "ملخص التقرير")
        self.report_btn = QPushButton("تفاصيل التقرير")
        self.report_btn.setObjectName("flat")
        self.report_btn.clicked.connect(self.show_report)
        named(self.report_btn, "تفاصيل التقرير", "كل الأرقام اللي طلعت من قراية الملف")
        self.queue_label = QLabel()
        self.queue_label.setObjectName("muted")
        named(self.queue_label, "ملفات مستنية")
        self.next_file_btn = QPushButton("الملف اللي بعده")
        self.next_file_btn.clicked.connect(self.nextFileRequested)
        named(self.next_file_btn, "الملف اللي بعده", "افتح الملف اللي مستني في القايمة")
        self.open_btn = QPushButton("ملف تاني…")
        self.open_btn.setToolTip("افتح ملف تاني (Ctrl+O)")
        self.open_btn.clicked.connect(self.openRequested)
        named(self.open_btn, "افتح ملف تاني", "Ctrl+O")
        self.save_btn = QPushButton("حفظ الملفات")
        self.save_btn.setObjectName("primary")
        self.save_btn.setToolTip("اعمل ملف Word وملف TXT (Ctrl+S)")
        self.save_btn.clicked.connect(self.saveRequested)
        named(self.save_btn, "حفظ الملفات", "اعمل ملف Word وملف TXT. اختصار Ctrl+S")
        row.addWidget(self.file_label)
        row.addWidget(self.report_label, 1)
        row.addWidget(self.report_btn)
        row.addSpacing(12)
        row.addWidget(self.queue_label)
        row.addWidget(self.next_file_btn)
        row.addWidget(self.open_btn)
        row.addWidget(self.save_btn)
        return header

    def _build_pages(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("الصفحات")
        title.setObjectName("muted")
        self.page_list = QListWidget()
        self.page_list.setIconSize(QSize(16, 16))
        self.page_list.setUniformItemSizes(True)
        self.page_list.setMinimumWidth(118)
        self.page_list.currentRowChanged.connect(self._row_changed)
        named(self.page_list, "قايمة الصفحات",
              "علامة صح خضرا = اتراجعت، مثلث برتقاني = فيها حاجات محتاجة مراجعة")
        title.setBuddy(self.page_list)
        layout.addWidget(title)
        layout.addWidget(self.page_list, 1)
        return panel

    def _build_text(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        named(self.page_title, "رقم الصفحة")
        self.chip = QLabel()
        self.chip.setContentsMargins(12, 1, 12, 1)
        named(self.chip, "حالة الصفحة")
        self.unmark_btn = QPushButton("شيل علامة المراجعة")
        self.unmark_btn.setObjectName("flat")
        self.unmark_btn.clicked.connect(self.unmark)
        named(self.unmark_btn, "شيل علامة المراجعة من الصفحة دي")
        top.addWidget(self.page_title)
        top.addWidget(self.chip)
        top.addWidget(self.unmark_btn)
        top.addStretch(1)
        layout.addLayout(top)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(10, 6, 10, 6)
        icon = QLabel()
        icon.setPixmap(status_pixmap("warn", 40).scaled(
            20, 20, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        named(self.banner_text, "تنبيهات الصفحة")
        banner_row.addWidget(icon)
        banner_row.addWidget(self.banner_text, 1)
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        self.editor = MarkupEditor()
        self.editor.setPlaceholderText(
            "مفيش كلام اتقرا من الصفحة دي. لو في الصورة كلام، اكتبه هنا.")
        self.editor.currentLineChanged.connect(self._line_changed)
        self.editor.userEdited.connect(self._edited)
        named(self.editor, "كلام الصفحة",
              "كل سطر فقرة. # في أول السطر يعني عنوان، > يعني برواز، (صورة: ...) كلام صورة")
        layout.addWidget(self.editor, 1)

        self.legend = QLabel(
            "<b>#</b> عنوان &nbsp;·&nbsp; <b>&gt;</b> برواز &nbsp;·&nbsp; <b>(صورة: …)</b> كلام صورة"
            " &nbsp;·&nbsp; <b>(صورة)</b> صورة بس &nbsp;·&nbsp; سطر فاضي يقفل البرواز")
        self.legend.setToolTip(chr(10).join([
            "# عنوان كبير، ## أصغر، ### أصغر، #### أصغر حاجة",
            "> في أول السطر: السطر جوه برواز (سطر فاضي بعده يقفل البرواز)",
            "(صورة: …) الكلام اللي مكتوب جوه صورة",
            "(صورة) مكان صورة مفيهاش كلام"]))
        self.legend.setObjectName("legend")
        self.legend.setWordWrap(True)
        named(self.legend, "طريقة الكتابة",
              "# عنوان، > برواز، (صورة: ...) كلام صورة، (صورة) صورة من غير كلام، "
              "وسطر فاضي يقفل البرواز")
        self.colors = QLabel(
            f"<span style='background:{BAD_BG}'>&nbsp;أحمر&nbsp;</span> حرف غلط أكيد "
            f"&nbsp;·&nbsp; <span style='background:{LOW_BG}'>&nbsp;برتقاني&nbsp;</span> "
            "سطر البرنامج مش متأكد منه &nbsp;·&nbsp; "
            f"<span style='background:{PLACED_BG}'>&nbsp;أصفر&nbsp;</span> برواز مكانه متخمّن")
        self.colors.setObjectName("legend")
        self.colors.setWordWrap(True)
        named(self.colors, "معنى الألوان",
              "أحمر حرف غلط أكيد، برتقاني سطر مش أكيد، أصفر برواز مكانه متخمن")
        layout.addWidget(self.legend)
        layout.addWidget(self.colors)
        return panel

    def _build_image(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        tools = QHBoxLayout()
        caption = QLabel("صورة الصفحة")
        caption.setObjectName("muted")
        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setToolTip("صغّر (Ctrl+-)")
        named(self.zoom_out_btn, "صغّر الصورة", "Ctrl+-")
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setToolTip("كبّر (Ctrl++)")
        named(self.zoom_in_btn, "كبّر الصورة", "Ctrl++")
        for btn in (self.zoom_out_btn, self.zoom_in_btn):
            btn.setFixedWidth(40)
        self.fit_btn = QPushButton("على قد العرض")
        self.fit_btn.setToolTip("خلّي الصورة على قد عرض المكان (Ctrl+0)")
        named(self.fit_btn, "الصورة على قد العرض", "Ctrl+0")
        self.zoom_label = QLabel()
        self.zoom_label.setObjectName("muted")
        self.zoom_label.setMinimumWidth(48)
        named(self.zoom_label, "حجم الصورة")
        tools.addWidget(caption)
        tools.addStretch(1)
        tools.addWidget(self.zoom_label)
        tools.addWidget(self.zoom_out_btn)
        tools.addWidget(self.zoom_in_btn)
        tools.addWidget(self.fit_btn)
        layout.addLayout(tools)

        self.view = PageView()
        named(self.view, "صورة الصفحة",
              "المستطيلات أماكن السطور. دوس على أي سطر في الصورة عشان تروح له في الكلام")
        self.view.pointClicked.connect(self._image_clicked)
        self.view.zoomChanged.connect(self._zoom_changed)
        self.zoom_out_btn.clicked.connect(self.view.zoom_out)
        self.zoom_in_btn.clicked.connect(self.view.zoom_in)
        self.fit_btn.clicked.connect(self.view.fit_width)

        self.no_image = QLabel("ملف Word: مفيش صورة للصفحة")
        self.no_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_image.setWordWrap(True)
        self.no_image.setObjectName("muted")
        self.no_image.setFrameShape(QFrame.Shape.StyledPanel)
        named(self.no_image, "مفيش صورة للصفحة")

        self.image_stack = QStackedWidget()
        self.image_stack.addWidget(self.view)
        self.image_stack.addWidget(self.no_image)
        layout.addWidget(self.image_stack, 1)
        self._image_tools = [self.zoom_out_btn, self.zoom_in_btn, self.fit_btn, self.zoom_label]
        return panel

    def _build_actions(self):
        bar = QFrame()
        bar.setObjectName("actionBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(8)
        style = self.style()
        self.prev_btn = QPushButton("السابق")
        self.prev_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.prev_btn.setToolTip("الصفحة اللي قبل كده (Ctrl+PgUp)")
        self.prev_btn.clicked.connect(self.prev_page)
        named(self.prev_btn, "الصفحة السابقة", "Ctrl+Page Up")
        self.next_btn = QPushButton("التالي")
        self.next_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.next_btn.setToolTip("الصفحة اللي بعدها (Ctrl+PgDn)")
        self.next_btn.clicked.connect(self.next_page)
        named(self.next_btn, "الصفحة التالية", "Ctrl+Page Down")
        self.problem_btn = QPushButton(f"المشكلة الجاية  {keys_hint('F8')}")
        self.problem_btn.setToolTip("روح للحتة اللي بعدها المتلوّنة (F8)")
        self.problem_btn.clicked.connect(self.next_problem)
        named(self.problem_btn, "المشكلة الجاية", "يروح لأقرب حتة متلونة بعد المؤشر. F8")
        self.picture_btn = QPushButton("إضافة كلام صورة")
        self.picture_btn.setToolTip("سطر جديد (صورة: ) تكتب فيه الكلام اللي جوه الصورة")
        self.picture_btn.clicked.connect(self.insert_picture)
        named(self.picture_btn, "إضافة كلام صورة",
              "يزود سطر (صورة: ) تحت السطر الحالي وتكتب جواه")
        self.progress_label = QLabel()
        self.progress_label.setObjectName("muted")
        named(self.progress_label, "عدد الصفحات اللي اتراجعت")
        self.done_btn = QPushButton(f"اتراجعت ✓  {keys_hint('Ctrl+Enter')}")
        self.done_btn.setObjectName("done")
        self.done_btn.setToolTip("علّم الصفحة إنها اتراجعت وروح للي بعدها (Ctrl+Enter)")
        self.done_btn.clicked.connect(self.mark_done)
        named(self.done_btn, "الصفحة اتراجعت",
              "علّم الصفحة إنها اتراجعت وروح للي بعدها. Ctrl+Enter")
        row.addWidget(self.prev_btn)
        row.addWidget(self.next_btn)
        row.addSpacing(10)
        row.addWidget(self.problem_btn)
        row.addWidget(self.picture_btn)
        row.addStretch(1)
        row.addWidget(self.progress_label)
        row.addSpacing(10)
        row.addWidget(self.done_btn)
        return bar

    def _make_actions(self):
        def action(name, keys, slot):
            act = QAction(name, self)
            act.setShortcuts([QKeySequence(k) for k in keys])
            act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            act.triggered.connect(slot)
            self.addAction(act)
            return act

        self.actions_by_name = {
            "prev": action("الصفحة السابقة", ["Ctrl+PgUp"], self.prev_page),
            "next": action("الصفحة التالية", ["Ctrl+PgDown"], self.next_page),
            "problem": action("المشكلة الجاية", ["F8"], self.next_problem),
            "done": action("اتراجعت", ["Ctrl+Return", "Ctrl+Enter"], self.mark_done),
            "save": action("حفظ الملفات", ["Ctrl+S"], self.saveRequested),
            "zoom_in": action("كبّر", ["Ctrl++", "Ctrl+="], self.view.zoom_in),
            "zoom_out": action("صغّر", ["Ctrl+-"], self.view.zoom_out),
            "fit": action("على قد العرض", ["Ctrl+0"], self.view.fit_width),
        }
        order = [self.page_list, self.editor, self.prev_btn, self.next_btn, self.problem_btn,
                 self.picture_btn, self.done_btn, self.view, self.zoom_out_btn, self.zoom_in_btn,
                 self.fit_btn, self.report_btn, self.next_file_btn, self.open_btn, self.save_btn]
        for first, second in zip(order, order[1:]):
            QWidget.setTabOrder(first, second)

    # ================================================================ document
    @property
    def page(self):
        return self.document.pages[self.index] if self.document and self.index >= 0 else None

    def set_document(self, document, reviewed=(), queue=0):
        self.close_document()
        self.document = document
        self.reviewed = set(reviewed)
        self.dirty = False
        self.save_error = None
        self.renderer = PdfRenderer(document.source) if document.kind == "pdf" else None
        self.file_label.setText(Path(document.source).name)
        self.file_label.setToolTip(str(document.source))
        self.report_label.setText(self.report_summary())
        self.report_label.setToolTip(self.report_summary())
        self.no_image.setText("ملف Word: مفيش صورة للصفحة" if document.kind != "pdf"
                              else "مقدرتش أعرض صورة الصفحة دي")
        for widget in self._image_tools:
            widget.setVisible(document.kind == "pdf")
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for i, page in enumerate(document.pages):
            item = QListWidgetItem(f"صفحة {ar(page.number)}")
            self.page_list.addItem(item)
            self._update_item(i)
        self.page_list.blockSignals(False)
        self.set_queue(queue)
        self.index = -1
        first = next((i for i, p in enumerate(document.pages) if p.number not in self.reviewed), 0)
        self.go_to(first)

    def close_document(self):
        self._timer.stop()
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        self.view.clear_page()
        self.document = None
        self.index = -1

    def set_queue(self, count):
        self.queue_label.setText(f"مستني: {ar(count)} ملف" if count else "")
        self.queue_label.setVisible(bool(count))
        self.next_file_btn.setVisible(bool(count))

    def report_summary(self):
        doc = self.document
        parts = [f"عدد الصفحات: {ar(len(doc.pages))}"]
        image_only = self.image_only_count()
        if image_only:
            parts.append(f"صفحات صورة بس: {ar(image_only)}")
        warned = sum(1 for p in doc.pages if p.warnings)
        if warned:
            parts.append(f"صفحات فيها تنبيهات: {ar(warned)}")
        return "  •  ".join(parts)

    def image_only_count(self):
        report = self.document.report if isinstance(self.document.report, dict) else {}
        for key in IMAGE_ONLY_KEYS:
            if key in report:
                count = count_of(report[key])
                if count is not None:
                    return count
        return sum(1 for p in self.document.pages if not page_has_text(p))

    def show_report(self):
        if self.document:
            ReportDialog(self.document, self).exec()

    # ================================================================ pages
    def go_to(self, index):
        if not self.document or not 0 <= index < len(self.document.pages):
            return
        if index == self.index:
            return
        if self.index >= 0:
            self.flush()
            if self.dirty:
                self.autosave()
        self.index = index
        page = self.page
        self.view.clear_page()
        self.editor.load_lines(page_lines(page))
        self._show_image(page)
        self._show_warnings(page)
        self._update_titles()
        self.page_list.blockSignals(True)
        self.page_list.setCurrentRow(index)
        self.page_list.blockSignals(False)
        self.page_list.scrollToItem(self.page_list.item(index))

    def _row_changed(self, row):
        if row >= 0:
            self.go_to(row)

    def prev_page(self):
        self.go_to(self.index - 1)

    def next_page(self):
        self.go_to(self.index + 1)

    def _show_image(self, page):
        if self.renderer is None:
            self.image_stack.setCurrentWidget(self.no_image)
            return
        try:
            image, size = self.renderer.render(page.number)
        except Exception as exc:   # damaged page, missing file ...
            self.view.clear_page()
            self.no_image.setText(f"مقدرتش أعرض صورة الصفحة دي.\n{exc}")
            self.image_stack.setCurrentWidget(self.no_image)
            return
        self.image_stack.setCurrentWidget(self.view)
        self.view.set_page(image, page.size or size, self.editor.boxes())
        self._line_changed(self.editor.current_data())

    def _show_warnings(self, page):
        warnings = [str(w) for w in page.warnings]
        self.banner.setVisible(bool(warnings))
        if warnings:
            self.banner_text.setText("<b>تنبيه على الصفحة دي:</b><br>"
                                     + "<br>".join("• " + _esc(w) for w in warnings))

    def _update_titles(self):
        page = self.page
        total = len(self.document.pages)
        self.page_title.setText(f"صفحة {ar(page.number)} من {ar(total)}")
        done = page.number in self.reviewed
        self.chip.setText("اتراجعت ✓" if done else "لسه متراجعتش")
        self.chip.setObjectName("chipDone" if done else "chipTodo")
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        self.chip.updateGeometry()
        self.unmark_btn.setVisible(done)
        count = sum(1 for p in self.document.pages if p.number in self.reviewed)
        self.progress_label.setText(f"اتراجع {ar(count)} من {ar(total)} صفحة")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < total - 1)

    def page_status(self, index):
        page = self.document.pages[index]
        if page.number in self.reviewed:
            return "done"
        return "warn" if page_needs_attention(page) else "none"

    def _update_item(self, index):
        item = self.page_list.item(index)
        if item is None:
            return
        status = self.page_status(index)
        page = self.document.pages[index]
        item.setIcon(status_icon(status))
        item.setData(Qt.ItemDataRole.AccessibleTextRole,
                     f"صفحة {page.number}، {STATUS_TEXT[status]}")
        tip = STATUS_TEXT[status]
        if page.warnings:
            tip += "\n" + "\n".join(str(w) for w in page.warnings)
        item.setToolTip(tip)
        item.setData(Qt.ItemDataRole.UserRole, status)

    # ================================================================ text <-> image
    def _line_changed(self, data):
        self.view.highlight(list(data.bboxes) if data is not None else [])

    def _image_clicked(self, x, y):
        line = self.editor.line_at_point(x, y)
        if line is not None:
            self.editor.select_spot(line)
            self.editor.setFocus()

    def _zoom_changed(self, zoom):
        self.zoom_label.setText(ar(round(zoom * 100)) + "٪")

    # ================================================================ editing
    def _edited(self):
        self.dirty = True
        self._timer.start()

    def flush(self):
        """Put the editor's text back into the current page if it was edited."""
        if self.index < 0 or not self.editor.document().isModified():
            return False
        self.page.blocks = self.editor.to_blocks()
        self.editor.document().setModified(False)
        self.dirty = True
        self._update_item(self.index)
        return True

    def autosave(self):
        """Save the review state next to the source. Returns False if that failed."""
        self._timer.stop()
        if not self.document:
            return True
        self.flush()
        if not self.dirty:
            return True
        try:
            self.saver(self.document, set(self.reviewed))
        except Exception as exc:
            self.save_error = str(exc) or exc.__class__.__name__
            self.message.emit("مقدرتش أحفظ المراجعة: " + self.save_error)
            return False
        self.dirty = False
        self.save_error = None
        self.message.emit("اتحفظت المراجعة " + ar(time.strftime("%H:%M")))
        return True

    def insert_picture(self):
        self.editor.insert_picture_line()

    def mark_done(self):
        if not self.page:
            return
        self.flush()
        self.reviewed.add(self.page.number)
        self.dirty = True
        self._update_item(self.index)
        self._update_titles()
        total = len(self.document.pages)
        if self.index + 1 < total:
            self.go_to(self.index + 1)
            return
        todo = next((i for i, p in enumerate(self.document.pages)
                     if p.number not in self.reviewed), None)
        if todo is not None:
            self.go_to(todo)
            self.message.emit("لسه فيه صفحات متراجعتش، رجعتك لأول واحدة فيهم.")
        else:
            self.autosave()
            self.message.emit("كل الصفحات اتراجعت ✓ تقدر تحفظ الملفات دلوقتي (Ctrl+S).")
            self.save_btn.setFocus()

    def unmark(self):
        if not self.page:
            return
        self.reviewed.discard(self.page.number)
        self.dirty = True
        self._update_item(self.index)
        self._update_titles()
        self._timer.start()

    def unreviewed_pages(self):
        return [p.number for p in self.document.pages if p.number not in self.reviewed]

    # ================================================================ F8
    def next_problem(self):
        """Go to the next highlighted spot: rest of this page, then the pages
        after it that are not reviewed yet, then around from the start."""
        if not self.document:
            return False
        start = self.editor.textCursor().selectionStart()
        qblock = self.editor.document().findBlock(start)
        here = (qblock.blockNumber(), start - qblock.position())
        spots = self.editor.spots()
        later = [s for s in spots if (s[0], s[1]) > here]
        if later:
            self._go_spot(self.index, later[0])
            return True
        total = len(self.document.pages)
        for step in range(1, total):
            i = (self.index + step) % total
            page = self.document.pages[i]
            if page.number in self.reviewed:
                continue
            found = spots_in_lines(page_lines(page))
            if found:
                self._go_spot(i, found[0])
                return True
        earlier = [s for s in spots if (s[0], s[1]) < here]
        if earlier:
            self._go_spot(self.index, earlier[0])
            return True
        self.message.emit("مفيش حاجات تانية متلوّنة محتاجة مراجعة.")
        return False

    def _go_spot(self, index, spot):
        self.go_to(index)
        line, start, length = spot
        self.editor.select_spot(line, start, length)
        self.editor.setFocus()

    # ================================================================ settings
    def _restore_splitter(self):
        state = settings().value("review/splitter")
        if state is not None:
            try:
                self.splitter.restoreState(state)
            except TypeError:
                pass

    def save_layout(self):
        s = settings()
        s.setValue("review/splitter", self.splitter.saveState())
        s.sync()
