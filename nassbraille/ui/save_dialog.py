"""Save dialog: where to write the Word/TXT files, and how they should look."""
from __future__ import annotations

import os
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QRadioButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .. import convert
from ..config import OutputOptions
from .common import ErrorDialog, ar, ar_list, ask, get_json, named, set_json
from .drives import drive_title, removable_drives

LRI, FSI, PDI = chr(0x2066), chr(0x2068), chr(0x2069)   # bidi isolates
RLM = chr(0x200F)   # right-to-left mark
ENCODINGS = [("utf-8-sig", "UTF-8 (الأحسن)"), ("utf-8", "UTF-8 بدون BOM"),
             ("cp1256", "Windows-1256")]
DIGITS = [("printed", "زي المطبوع"), ("western", "123"), ("arabic", "١٢٣")]


def ltr(text):
    """Keep a path or a drive letter in one left-to-right piece inside Arabic text."""
    return LRI + str(text) + PDI


def own_direction(text):
    """A file name shown in its own direction (Arabic names RTL, Latin names LTR)."""
    return FSI + str(text) + PDI


def load_options():
    return OutputOptions.from_dict(get_json("output/options", {}))


def store_options(opts):
    set_json("output/options", opts.to_dict())


class SaveDialog(QDialog):
    """exec() it, or drive it from code: choose_*(), set_options(), save()."""

    def __init__(self, document, reviewed, parent=None, has_next=False,
                 drives=removable_drives, confirm=None, error=None):
        super().__init__(parent)
        self.document = document
        self.reviewed = set(reviewed)
        self.has_next = has_next
        self.drives_func = drives
        self.confirm = confirm or self._ask_unreviewed
        self.error = error or self._show_error
        self.written = None      # write_outputs() result
        self.out_dir = None
        self.next_requested = False
        self.custom_dir = None
        self._drive_buttons = []
        self.setWindowTitle("حفظ الملفات")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(620)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_form())
        self.stack.addWidget(self._build_result())
        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)
        self._load_settings()
        self._update_state()

    # ================================================================ form
    def _build_form(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        todo = self.unreviewed()
        self.todo_banner = QFrame()
        self.todo_banner.setObjectName("banner")
        row = QHBoxLayout(self.todo_banner)
        row.setContentsMargins(10, 6, 10, 6)
        self.todo_label = QLabel()
        self.todo_label.setWordWrap(True)
        row.addWidget(self.todo_label)
        if todo:
            self.todo_label.setText(
                f"لسه فيه {ar(len(todo))} صفحة متعلّمش عليها إنها اتراجعت "
                f"(صفحة {ar_list(todo, 12)}). تقدر تحفظ دلوقتي وتكمل المراجعة بعدين.")
            named(self.todo_label, self.todo_label.text())
        self.todo_banner.setVisible(bool(todo))
        layout.addWidget(self.todo_banner)

        # ---- where
        where = QGroupBox("فين أحفظ الملفات؟")
        self.where_layout = QVBoxLayout(where)
        self.dest_group = QButtonGroup(self)
        self.same_radio = QRadioButton("نفس فولدر الملف")
        named(self.same_radio, "نفس فولدر الملف")
        source_dir = Path(self.document.source).parent
        self.same_path = QLabel(RLM + ltr(source_dir))
        self.same_path.setObjectName("muted")
        self.same_path.setIndent(28)
        self.dest_group.addButton(self.same_radio)
        self.where_layout.addWidget(self.same_radio)
        self.where_layout.addWidget(self.same_path)

        self.drives_box = QVBoxLayout()
        self.where_layout.addLayout(self.drives_box)
        drive_row = QHBoxLayout()
        self.no_drive_label = QLabel("مفيش فلاشة متوصلة دلوقتي.")
        self.no_drive_label.setObjectName("muted")
        self.no_drive_label.setIndent(28)
        self.rescan_btn = QPushButton("دوّر على الفلاشات تاني")
        self.rescan_btn.setObjectName("flat")
        self.rescan_btn.clicked.connect(self.refresh_drives)
        named(self.rescan_btn, "دور على الفلاشات تاني")
        drive_row.addWidget(self.no_drive_label)
        drive_row.addStretch(1)
        drive_row.addWidget(self.rescan_btn)
        self.where_layout.addLayout(drive_row)

        custom_row = QHBoxLayout()
        self.custom_radio = QRadioButton("اختار فولدر…")
        named(self.custom_radio, "اختار فولدر")
        self.dest_group.addButton(self.custom_radio)
        self.custom_btn = QPushButton("اختار…")
        self.custom_btn.clicked.connect(self.browse)
        named(self.custom_btn, "اختار الفولدر")
        custom_row.addWidget(self.custom_radio)
        custom_row.addStretch(1)
        custom_row.addWidget(self.custom_btn)
        self.where_layout.addLayout(custom_row)
        self.custom_path = QLabel()
        self.custom_path.setObjectName("muted")
        self.custom_path.setIndent(28)
        self.where_layout.addWidget(self.custom_path)
        self.custom_radio.toggled.connect(self._custom_toggled)
        self.dest_group.buttonToggled.connect(lambda *_: self._update_state())
        layout.addWidget(where)

        # ---- what
        what = QGroupBox("الملفات اللي هتتعمل")
        what_layout = QGridLayout(what)
        self.docx_check = QCheckBox("ملف Word")
        named(self.docx_check, "اعمل ملف Word")
        self.txt_check = QCheckBox("ملف TXT")
        named(self.txt_check, "اعمل ملف TXT")
        self.docx_check.toggled.connect(self._update_state)
        self.txt_check.toggled.connect(self._update_state)
        enc_label = QLabel("ترميز ملف TXT:")
        self.encoding_combo = QComboBox()
        for value, label in ENCODINGS:
            self.encoding_combo.addItem(label, value)
        named(self.encoding_combo, "ترميز ملف TXT")
        enc_label.setBuddy(self.encoding_combo)
        self.encoding_combo.currentIndexChanged.connect(self._update_state)
        self.enc_warning = QLabel(
            "تنبيه: Windows-1256 مفيهوش الأرقام العربي (١٢٣) وبعض الرموز، "
            "وأي حاجة منهم هتتكتب علامة استفهام (?). الأحسن UTF-8، "
            "أو اختار الأرقام 123 تحت.")
        self.enc_warning.setWordWrap(True)
        self.enc_warning.setObjectName("warnText")
        named(self.enc_warning, self.enc_warning.text())
        what_layout.addWidget(self.docx_check, 0, 0)
        what_layout.addWidget(self.txt_check, 0, 1)
        what_layout.addWidget(enc_label, 1, 0)
        what_layout.addWidget(self.encoding_combo, 1, 1)
        what_layout.addWidget(self.enc_warning, 2, 0, 1, 2)
        layout.addWidget(what)

        # ---- how
        how = QGroupBox("شكل الكلام")
        how_layout = QVBoxLayout(how)
        self.markers_check = QCheckBox("علامة صفحة N في أول كل صفحة")
        self.markers_check.setToolTip("بيكتب «صفحة ١»، «صفحة ٢» … عشان الطالبة تعرف هي في أنهي صفحة")
        named(self.markers_check, "علامة صفحة N في أول كل صفحة")
        self.pictures_check = QCheckBox("اكتب (صورة) مكان الصور")
        self.pictures_check.setToolTip("مكان كل صورة اتشالت ومفيهاش كلام يتكتب (صورة)")
        named(self.pictures_check, "اكتب كلمة صورة مكان الصور")
        digits_row = QHBoxLayout()
        digits_label = QLabel("الأرقام:")
        digits_row.addWidget(digits_label)
        self.digit_group = QButtonGroup(self)
        self.digit_radios = {}
        for value, label in DIGITS:
            radio = QRadioButton(label)
            named(radio, "الأرقام " + label)
            self.digit_group.addButton(radio)
            self.digit_radios[value] = radio
            digits_row.addWidget(radio)
        digits_row.addStretch(1)
        how_layout.addWidget(self.markers_check)
        how_layout.addLayout(digits_row)
        how_layout.addWidget(self.pictures_check)
        layout.addWidget(how)

        # ---- buttons
        buttons = QHBoxLayout()
        self.hint_label = QLabel()
        self.hint_label.setObjectName("muted")
        self.save_btn = QPushButton("احفظ")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.save)
        named(self.save_btn, "احفظ الملفات")
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        named(cancel, "إلغاء")
        buttons.addWidget(self.hint_label, 1)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        return page

    # ================================================================ result
    def _build_result(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        self.result_title = QLabel("اتحفظت الملفات ✓")
        self.result_title.setObjectName("resultTitle")
        named(self.result_title, "اتحفظت الملفات")
        layout.addWidget(self.result_title)
        self.result_files = QLabel()
        self.result_files.setWordWrap(True)
        self.result_files.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        named(self.result_files, "أماكن الملفات")
        layout.addWidget(self.result_files)
        self.lost_banner = QFrame()
        self.lost_banner.setObjectName("banner")
        lost_row = QHBoxLayout(self.lost_banner)
        lost_row.setContentsMargins(10, 6, 10, 6)
        self.lost_label = QLabel()
        self.lost_label.setWordWrap(True)
        named(self.lost_label, "تنبيه الترميز")
        lost_row.addWidget(self.lost_label)
        layout.addWidget(self.lost_banner)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        self.open_folder_btn = QPushButton("افتح الفولدر")
        self.open_folder_btn.clicked.connect(self.open_folder)
        named(self.open_folder_btn, "افتح الفولدر")
        self.next_btn = QPushButton("الملف اللي بعده")
        self.next_btn.clicked.connect(self._next_file)
        named(self.next_btn, "افتح الملف اللي بعده")
        self.next_btn.setVisible(self.has_next)
        done = QPushButton("تمام")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        named(done, "تمام")
        self._done_btn = done
        buttons.addWidget(self.open_folder_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.next_btn)
        buttons.addWidget(done)
        layout.addLayout(buttons)
        return page

    # ================================================================ state
    def unreviewed(self):
        return [p.number for p in self.document.pages if p.number not in self.reviewed]

    def refresh_drives(self):
        previous = self.selected_drive()
        for btn in self._drive_buttons:
            self.dest_group.removeButton(btn)
            btn.deleteLater()
        self._drive_buttons = []
        try:
            drives = list(self.drives_func())
        except Exception:
            drives = []
        for root, label in drives:
            btn = QRadioButton(drive_title(root, label))
            btn.setProperty("root", root)
            btn.setProperty("label", label)
            named(btn, drive_title(root, label))
            self.dest_group.addButton(btn)
            self.drives_box.addWidget(btn)
            self._drive_buttons.append(btn)
        self.no_drive_label.setVisible(not drives)
        if previous:
            for btn in self._drive_buttons:
                if btn.property("root") == previous:
                    btn.setChecked(True)
        if self.dest_group.checkedButton() is None:
            self.same_radio.setChecked(True)
        self._update_state()

    def selected_drive(self):
        btn = self.dest_group.checkedButton()
        if btn in self._drive_buttons:
            return btn.property("root")
        return None

    def destination(self):
        """The chosen output folder, or None (custom folder not picked yet)."""
        btn = self.dest_group.checkedButton()
        if btn is self.same_radio:
            return Path(self.document.source).parent
        if btn is self.custom_radio:
            return Path(self.custom_dir) if self.custom_dir else None
        if btn in self._drive_buttons:
            return Path(btn.property("root"))
        return None

    def choose_same(self):
        self.same_radio.setChecked(True)

    def choose_drive(self, root):
        for btn in self._drive_buttons:
            if btn.property("root") == root:
                btn.setChecked(True)
                return True
        return False

    def choose_custom(self, path):
        self.custom_dir = str(path)
        self.custom_path.setText(RLM + ltr(self.custom_dir))
        self.custom_radio.blockSignals(True)
        self.custom_radio.setChecked(True)
        self.custom_radio.blockSignals(False)
        self._update_state()

    def _custom_toggled(self, on):
        if on and not self.custom_dir:
            self.browse()
        self._update_state()

    def browse(self):
        start = self.custom_dir or str(Path(self.document.source).parent)
        folder = QFileDialog.getExistingDirectory(self, "اختار الفولدر اللي هتتحفظ فيه الملفات",
                                                  start)
        if folder:
            self.choose_custom(folder)
        elif not self.custom_dir:
            self.same_radio.setChecked(True)

    def options(self):
        opts = self._base_options
        digits = next((v for v, r in self.digit_radios.items() if r.isChecked()), "printed")
        return OutputOptions(
            write_docx=self.docx_check.isChecked(),
            write_txt=self.txt_check.isChecked(),
            page_markers=self.markers_check.isChecked(),
            digits=digits,
            picture_markers=self.pictures_check.isChecked(),
            txt_encoding=self.encoding_combo.currentData() or "utf-8-sig",
            font=opts.font, base_size=opts.base_size, line_spacing=opts.line_spacing)

    def set_options(self, opts):
        self._base_options = opts
        self.docx_check.setChecked(opts.write_docx)
        self.txt_check.setChecked(opts.write_txt)
        self.markers_check.setChecked(opts.page_markers)
        self.pictures_check.setChecked(opts.picture_markers)
        self.digit_radios.get(opts.digits, self.digit_radios["printed"]).setChecked(True)
        index = self.encoding_combo.findData(opts.txt_encoding)
        self.encoding_combo.setCurrentIndex(index if index >= 0 else 0)
        self._update_state()

    def _load_settings(self):
        self.set_options(load_options())
        dest = get_json("output/dest", {})
        dest = dest if isinstance(dest, dict) else {}
        self.custom_dir = dest.get("custom") if isinstance(dest.get("custom"), str) else None
        if self.custom_dir:
            self.custom_path.setText(RLM + ltr(self.custom_dir))
        self.custom_radio.blockSignals(True)
        self.refresh_drives()
        kind = dest.get("kind")
        if self._drive_buttons and kind in (None, "usb"):
            wanted = dest.get("label")
            match = [b for b in self._drive_buttons if wanted and b.property("label") == wanted]
            (match or self._drive_buttons)[0].setChecked(True)
        elif kind == "custom" and self.custom_dir and Path(self.custom_dir).is_dir():
            self.custom_radio.setChecked(True)
        else:
            self.same_radio.setChecked(True)
        self.custom_radio.blockSignals(False)
        self._update_state()

    def _store_settings(self):
        store_options(self.options())
        btn = self.dest_group.checkedButton()
        kind = "same" if btn is self.same_radio else "custom" if btn is self.custom_radio else "usb"
        set_json("output/dest", {"kind": kind, "custom": self.custom_dir,
                                 "label": btn.property("label") if kind == "usb" else None})

    def _update_state(self, *_):
        if not hasattr(self, "save_btn"):
            return
        self.encoding_combo.setEnabled(self.txt_check.isChecked())
        self.enc_warning.setVisible(self.txt_check.isChecked()
                                    and self.encoding_combo.currentData() == "cp1256")
        nothing = not (self.docx_check.isChecked() or self.txt_check.isChecked())
        no_dest = self.destination() is None
        self.save_btn.setEnabled(not nothing and not no_dest)
        if nothing:
            self.hint_label.setText("اختار ملف Word أو TXT على الأقل.")
        elif no_dest:
            self.hint_label.setText("اختار الفولدر الأول.")
        else:
            self.hint_label.setText("")

    # ================================================================ actions
    def _ask_unreviewed(self, todo):
        return ask(self, "فيه صفحات متراجعتش",
                   f"لسه فيه {ar(len(todo))} صفحة متراجعتش. تحفظ الملفات برضه؟\n"
                   "(ممكن ترجع تكمّل المراجعة وتحفظ تاني بعدين)",
                   yes="احفظ برضه", no="ارجع أراجع")

    def _show_error(self, message, details):
        ErrorDialog(self, message, details).exec()

    def save(self):
        """Write the files. Returns True when they were written."""
        out_dir = self.destination()
        opts = self.options()
        if out_dir is None or not (opts.write_docx or opts.write_txt):
            self._update_state()
            return False
        todo = self.unreviewed()
        if todo and not self.confirm(todo):
            return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = convert.write_outputs(self.document, out_dir, opts)
        except PermissionError as exc:
            QApplication.restoreOverrideCursor()
            self.error("مقدرتش أكتب الملفات. لو الملف مفتوح في Word اقفله وجرّب تاني، "
                       "واتأكد إن الفلاشة مش مقفولة للكتابة.", f"{exc}\n\n{traceback.format_exc()}")
            return False
        except OSError as exc:
            QApplication.restoreOverrideCursor()
            self.error("مقدرتش أكتب الملفات في الفولدر ده. اتأكد إن الفلاشة لسه متوصلة "
                       "وإن فيها مكان فاضي، أو اختار فولدر تاني.",
                       f"{exc}\n\n{traceback.format_exc()}")
            return False
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self.error("حصلت مشكلة وإحنا بنكتب الملفات.", f"{exc}\n\n{traceback.format_exc()}")
            return False
        QApplication.restoreOverrideCursor()
        self.written = result
        self.out_dir = Path(out_dir)
        self._store_settings()
        self._show_result(result, opts)
        return True

    def _show_result(self, result, opts):
        lines = [f"<b>في الفولدر:</b><br>{RLM}{ltr(_esc(self.out_dir))}"]
        if result.get("docx"):
            lines.append(f"<b>ملف Word:</b> {own_direction(_esc(Path(result['docx']).name))}")
        if result.get("txt"):
            lines.append(f"<b>ملف TXT:</b> {own_direction(_esc(Path(result['txt']).name))}")
        self.result_files.setText("<br><br>".join(lines))
        full_paths = [str(result[k]) for k in ("docx", "txt") if result.get(k)]
        self.result_files.setToolTip(chr(10).join(full_paths))
        lost = int(result.get("lost") or 0)
        if lost > 0:
            self.lost_label.setText(
                f"<b>تنبيه:</b> عدد الحروف اللي مينفعش تتكتب في ملف TXT بترميز "
                f"{ltr('Windows-1256')}: {ar(lost)}. اتحط مكانها علامة استفهام (?). "
                f"لو عايز الكلام كله زي ما هو، احفظ تاني واختار {ltr('UTF-8')}.")
        self.lost_banner.setVisible(lost > 0)
        self.stack.setCurrentIndex(1)
        self.save_btn.setDefault(False)        # Enter now means «تمام», never «احفظ» again
        self._done_btn.setDefault(True)
        self._done_btn.setFocus()

    def open_folder(self):
        if self.out_dir and hasattr(os, "startfile"):
            try:
                os.startfile(str(self.out_dir))
            except OSError as exc:
                self.error("مقدرتش أفتح الفولدر.", str(exc))

    def _next_file(self):
        self.next_requested = True
        self.accept()


def _esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
