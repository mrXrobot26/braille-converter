"""Drive the GUI offscreen with the fake reader and check the main flows.

    .venv\\Scripts\\python.exe tests\\test_ui_smoke.py      (also works under pytest)

Screenshots go to build/ui_shots/. The review-state file this creates next to
the fixture (original.pdf.nassbraille.json) is removed again at the end.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "build" / "ui_shots"
FIXTURE_PDF = ROOT / "tests" / "fixtures" / "saifi" / "original.pdf"


ENV_KEYS = ("QT_QPA_PLATFORM", "NASSBRAILLE_FAKE", "NASSBRAILLE_FAKE_DELAY",
            "NASSBRAILLE_SETTINGS")


def _environment(tmp):
    """Set the variables the test needs; returns the old values to restore."""
    saved = {key: os.environ.get(key) for key in ENV_KEYS}
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["NASSBRAILLE_FAKE"] = "1"
    os.environ["NASSBRAILLE_FAKE_DELAY"] = "0"
    os.environ["NASSBRAILLE_SETTINGS"] = str(tmp / "settings.ini")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return saved


def _restore(saved):
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _wait(app, condition, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    app.processEvents()
    return condition()


def _shot(widget, name, app):
    app.processEvents()
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    assert widget.grab().save(str(path)), path
    return path


def _type(widget, text):
    """Type text like a keyboard would (QTest.keyClicks only handles ASCII)."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    for ch in text:
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            event = QKeyEvent(kind, Qt.Key.Key_unknown if ch != " " else Qt.Key.Key_Space,
                              Qt.KeyboardModifier.NoModifier, ch)
            QApplication.sendEvent(widget, event)


def _same_block(a, b):
    return (a.kind, a.text, list(map(tuple, a.bboxes)), a.confidence, list(a.flags)) == \
           (b.kind, b.text, list(map(tuple, b.bboxes)), b.confidence, list(b.flags))


def check_pure_logic():
    from nassbraille.model import page_to_markup
    from nassbraille.ui import dev_fake
    from nassbraille.ui.markup_editor import page_lines
    from nassbraille.model import Block, Page
    from nassbraille.ui.problems import (
        bad_char_positions, line_spots, page_needs_attention, spots_in_lines,
    )
    from nassbraille.ui.review_screen import format_value

    doc = dev_fake.read_document(FIXTURE_PDF)
    assert len(doc.pages) == 58
    for page in doc.pages:
        text = "\n".join(t for t, _ in page_lines(page))
        assert text == page_to_markup(page), page.number
        for block in page.blocks:
            assert block.bboxes, (page.number, block.text)
    assert bad_char_positions("الدو\ue02aلة") == [4]
    assert bad_char_positions("الدوJلة") == [4]
    assert bad_char_positions("ملف PDF و(Word)") == []
    assert bad_char_positions("x\ufffd") == [1]
    assert bad_char_positions("كَتbَ") == [3]
    assert line_spots("", None) == []
    assert bad_char_positions("مادة ١٠١: «نص» – (صورة) ...") == []

    # a yellow box of three lines is one F8 stop; a red letter inside is its own stop
    placed = Block("box", "x", flags=["placed-box"])
    lines = [("أ", None), ("> ب", placed), ("> ج", placed), ("> د" + chr(0xFFFD), placed),
             ("", None), ("> هـ", placed)]
    assert spots_in_lines(lines) == [(1, 0, 0), (3, 3, 1), (5, 0, 0)], spots_in_lines(lines)
    # a guessed box position alone is highlighted but does not put a warning on the page
    assert not page_needs_attention(Page(1, [Block("box", "نص", flags=["placed-box"])]))
    assert page_needs_attention(Page(1, [Block("para", "نص", flags=["suspect-words"])]))
    assert page_needs_attention(Page(1, [Block("para", "نص")], ["تنبيه"]))

    # report values the way the real readers give them
    assert format_value({"tagged": 56, "geometric": 2}).startswith("من الترتيب المتسجل")
    fonts = {"Sultan bold#1": {"choice": "font"}, "VEXA#2": {"choice": "font"}}
    assert format_value(fonts).startswith("Sultan bold#1، VEXA#2")
    assert format_value([1, 24, 42]) == "١، ٢٤، ٤٢  (العدد: ٣)"
    assert format_value(True) == "أيوه" and format_value("arabic") == "١٢٣"
    return doc


def check_editor_round_trip(app, doc):
    """Unchanged text gives back the same blocks; split + join keeps the link."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from nassbraille.model import markup_to_blocks, page_to_markup
    from nassbraille.ui.markup_editor import MarkupEditor, page_lines

    editor = MarkupEditor()
    editor.resize(600, 400)
    editor.show()
    for page in doc.pages[:12]:
        editor.load_lines(page_lines(page))
        blocks = editor.to_blocks()
        assert len(blocks) == len(page.blocks), page.number
        assert all(_same_block(a, b) for a, b in zip(blocks, page.blocks)), page.number
        # parsing the plain text gives the same structure as the model does
        plain = [(b.kind, b.text, b.box_id) for b in markup_to_blocks(page_to_markup(page))]
        mine = [(b.kind, b.text, b.box_id) for b in blocks]
        assert plain == mine, page.number

    page = doc.pages[1]
    editor.load_lines(page_lines(page))
    target = next(n for n, (t, b) in enumerate(page_lines(page)) if b is not None and len(t) > 30)
    qblock = editor.document().findBlockByNumber(target)
    original = editor.line_data(qblock).bboxes
    editor.select_spot(target, 10)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    upper = editor.document().findBlockByNumber(target)
    lower = upper.next()
    assert editor.line_data(upper).bboxes == original
    assert editor.line_data(lower).bboxes == original, "split line lost its image link"
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    joined = editor.document().findBlockByNumber(target)
    assert editor.line_data(joined).bboxes == original
    blocks = editor.to_blocks()
    assert all(_same_block(a, b) for a, b in zip(blocks, page.blocks)), "split+join changed text"
    # Shift+Enter must not leave a hidden line separator in the text
    editor.select_spot(target, 5)
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert "\u2028" not in editor.toPlainText()
    editor.close()
    editor.deleteLater()


def check_formats(editor, char, color):
    """True when the editor shows `char` with the background `color`."""
    from PySide6.QtGui import QColor
    qblock = editor.document().firstBlock()
    while qblock.isValid():
        pos = qblock.text().find(char) if char else (0 if qblock.text() else -1)
        if pos >= 0:
            for rng in qblock.layout().formats():
                bg = rng.format.background().color()
                if rng.start <= pos < rng.start + rng.length and bg == QColor(color):
                    return True
        qblock = qblock.next()
    return False


def check_line_color(editor, level, color):
    """Some line of `level` ('low'/'placed') starts with the background `color`."""
    from PySide6.QtGui import QColor

    from nassbraille.ui.problems import bad_char_positions, line_level
    qblock = editor.document().firstBlock()
    while qblock.isValid():
        data = editor.line_data(qblock)
        if data is not None and line_level(data) == level and qblock.text()                 and 0 not in bad_char_positions(qblock.text()):
            return any(rng.start == 0 and rng.format.background().color() == QColor(color)
                       for rng in qblock.layout().formats())
        qblock = qblock.next()
    return False


def missing_names(root):
    """Controls the helper can reach that have no accessible name."""
    from PySide6.QtWidgets import (
        QAbstractButton, QComboBox, QGraphicsView, QListWidget, QPlainTextEdit, QProgressBar,
        QScrollBar, QWidget,
    )
    kinds = (QAbstractButton, QComboBox, QListWidget, QPlainTextEdit, QGraphicsView, QProgressBar)
    missing = []
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, kinds):
            continue
        parent, inner = widget.parentWidget(), False
        while parent is not None and parent is not root:
            if isinstance(parent, (QComboBox, QScrollBar)):
                inner = True     # Qt's own parts of a combo box or scroll bar
                break
            parent = parent.parentWidget()
        if not inner and not widget.accessibleName():
            text = widget.text() if hasattr(widget, "text") else ""
            missing.append((type(widget).__name__, text))
    return missing


def run(shots=True):
    tmp = Path(tempfile.mkdtemp(prefix="nassbraille_ui_"))
    saved_env = _environment(tmp)
    from nassbraille.project import load_project, project_path

    proj = project_path(FIXTURE_PDF)
    backup = tmp / "backup.json"
    if proj.exists():
        shutil.move(str(proj), str(backup))
    try:
        _run(tmp, shots)
    finally:
        for leftover in (proj, proj.with_name(proj.name + ".tmp")):
            if leftover.exists():
                leftover.unlink()
        if backup.exists():
            shutil.move(str(backup), str(proj))
        shutil.rmtree(tmp, ignore_errors=True)
        _restore(saved_env)
    assert load_project is not None


def _run(tmp, shots):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest

    from nassbraille.model import page_to_markup
    from nassbraille.project import load_project, project_path
    from nassbraille.ui.app import create_application
    from nassbraille.ui.common import ErrorDialog
    from nassbraille.ui.drives import removable_drives
    from nassbraille.ui.main_window import MainWindow
    from nassbraille.ui.markup_editor import BAD_BG, LOW_BG, page_lines
    from nassbraille.ui.problems import line_spots
    from nassbraille.ui.reading import UNEXPECTED
    from nassbraille.ui.review_screen import ReportDialog
    from nassbraille.ui.save_dialog import SaveDialog, load_options

    app = create_application(["test"])
    shoot = (lambda w, n: _shot(w, n, app)) if shots else (lambda w, n: None)

    doc0 = check_pure_logic()
    check_editor_round_trip(app, doc0)
    assert isinstance(removable_drives(), list)

    # ------------------------------------------------------------ start screen
    errors, questions = [], []
    w = MainWindow()
    w.resize(1366, 768)
    w.show()
    w.ask = lambda title, text, yes="", no="": questions.append(text) or True
    w.inform = lambda *a, **k: errors.append(a)
    w.show_error = lambda message, details="": errors.append((message, details))
    app.processEvents()
    assert w.stack.currentWidget() is w.start
    shoot(w, "01_start.png")

    # ------------------------------------------------------------ reading
    os.environ["NASSBRAILLE_FAKE_DELAY"] = "0.03"
    w.open_files([str(FIXTURE_PDF)])
    assert w.stack.currentWidget() is w.reading
    assert _wait(app, lambda: w.reading.bar.value() >= 12)
    shoot(w, "02_reading.png")
    os.environ["NASSBRAILLE_FAKE_DELAY"] = "0"
    assert _wait(app, lambda: w.stack.currentWidget() is w.review), errors
    assert not errors, errors
    assert not questions, "no saved review yet, nothing to ask"

    r = w.review
    doc = r.document
    assert len(doc.pages) == 58 and r.index == 0
    assert r.editor.toPlainText() == page_to_markup(doc.pages[0])
    assert r.banner.isVisible(), "page 1 has a warning"
    assert r.page_list.item(0).data(Qt.ItemDataRole.UserRole) == "warn"
    assert "عدد الصفحات" in r.report_label.text()
    shoot(w, "03_review_page1.png")
    assert not missing_names(w), missing_names(w)
    w.resize(1024, 640)
    shoot(w, "12_review_small_window.png")
    w.resize(1366, 768)
    app.processEvents()

    # ------------------------------------------------------------ text <-> image
    r.go_to(1)
    page = doc.pages[1]
    assert r.view.has_page()
    assert r.view.box_count() == sum(len(b.bboxes) for b in page.blocks)
    assert not r.banner.isVisible()
    lines = page_lines(page)
    line_no = next(n for n, (t, b) in enumerate(lines) if b is not None and len(b.bboxes) == 2)
    r.editor.select_spot(line_no)
    app.processEvents()
    marked = r.view.marked_rects()
    assert len(marked) == 2
    assert marked[0] == r.view.to_pixels(lines[line_no][1].bboxes[0])

    target = next(n for n, (t, b) in enumerate(lines) if b is not None and n > line_no + 2)
    center = r.view.to_pixels(lines[target][1].bboxes[0]).center()
    r.view.ensureVisible(r.view.to_pixels(lines[target][1].bboxes[0]))
    app.processEvents()
    pos = r.view.mapFromScene(center)
    QTest.mouseClick(r.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(pos.x(), pos.y()))
    app.processEvents()
    assert r.editor.textCursor().blockNumber() == target, "click on image -> line"

    # red / orange highlights on page 2 (fake: broken glyph + low confidence)
    assert check_formats(r.editor, "\ue02a", BAD_BG), "PUA char should be red"
    assert check_line_color(r.editor, "low", LOW_BG), "unsure line should be orange"
    shoot(w, "04_review_page2_link.png")

    # ------------------------------------------------------------ editing
    edit_no = next(n for n, (t, b) in enumerate(lines)
                   if b is not None and b.kind == "para" and "\ue02a" not in t and n != target)
    before_blocks = [b for b in page.blocks]
    edited_source = lines[edit_no][1]
    cursor = QTextCursor(r.editor.document().findBlockByNumber(edit_no))
    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    r.editor.setTextCursor(cursor)
    _type(r.editor, " تجربة")
    assert r.editor.document().isModified() and r.dirty
    assert r._timer.isActive(), "autosave is waiting"
    r.go_to(2)                       # leaving the page parses it back and autosaves
    assert project_path(FIXTURE_PDF).exists()
    after = doc.pages[1].blocks
    assert len(after) == len(before_blocks)
    changed = [i for i, (a, b) in enumerate(zip(after, before_blocks)) if not _same_block(a, b)]
    assert len(changed) == 1, changed
    new_block = after[changed[0]]
    assert new_block.text == edited_source.text + " تجربة"
    assert new_block.bboxes == edited_source.bboxes, "edited line keeps its boxes"
    saved, saved_reviewed = load_project(FIXTURE_PDF)
    assert saved.pages[1].blocks[changed[0]].text.endswith("تجربة")

    # picture text on page 3
    r.editor.select_spot(0)
    r.picture_btn.click()
    cur = r.editor.textCursor()
    assert cur.block().text() == "(صورة: )"
    assert cur.positionInBlock() == len("(صورة: ")
    _type(r.editor, "خريطة")
    assert r.editor.textCursor().block().text() == "(صورة: خريطة)"
    assert r.editor.line_data(r.editor.textCursor().block()) is None, "new line has no box"
    r.flush()
    assert any(b.kind == "caption" and b.text == "(صورة: خريطة)" and not b.bboxes
               for b in doc.pages[2].blocks)

    # ------------------------------------------------------------ F8
    r.go_to(1)
    r.editor.select_spot(0)
    visited = []
    for _ in range(6):
        assert r.next_problem()
        cur = r.editor.textCursor()
        qb = cur.block()
        spot = (cur.selectionStart() - qb.position(), cur.selectionEnd() - cur.selectionStart())
        page_now = doc.pages[r.index]
        info = r.editor.line_data(qb)
        assert spot in line_spots(qb.text(), info), (r.index, qb.text()[:30], spot)
        visited.append((page_now.number, qb.blockNumber(), spot))
    assert any(p == 2 and s[1] == 1 for p, _, s in visited), visited
    assert len(set(visited)) == len(visited), "F8 moves forward"

    # ------------------------------------------------------------ reviewed marks
    r.go_to(0)
    r.editor.setFocus()
    QTest.keyClick(r.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert 1 in r.reviewed and r.index == 1, (r.reviewed, r.index)
    assert r.page_list.item(0).data(Qt.ItemDataRole.UserRole) == "done"
    r.actions_by_name["done"].trigger()
    assert 2 in r.reviewed and r.index == 2
    QTest.keyClick(r.editor, Qt.Key.Key_PageUp, Qt.KeyboardModifier.ControlModifier)
    assert r.index == 1
    QTest.keyClick(r.editor, Qt.Key.Key_PageDown, Qt.KeyboardModifier.ControlModifier)
    assert r.index == 2
    # debounced autosave fires by itself after 2 s
    _type(r.editor, "ا")
    assert r._timer.isActive()
    assert _wait(app, lambda: not r.dirty, 4.0), "autosave after 2 s"
    QTest.keyClick(r.editor, Qt.Key.Key_Backspace)
    shoot(w, "05_review_page3_reviewed.png")

    # ------------------------------------------------------------ close + resume
    w.close()
    app.processEvents()
    saved, saved_reviewed = load_project(FIXTURE_PDF)
    assert saved_reviewed == {1, 2}, saved_reviewed
    assert any(b.text.endswith("تجربة") for b in saved.pages[1].blocks)

    w2 = MainWindow()
    w2.resize(1366, 768)
    w2.show()
    questions.clear()
    w2.ask = lambda title, text, yes="", no="": questions.append(text) or True
    w2.inform = lambda *a, **k: errors.append(a)
    w2.show_error = lambda message, details="": errors.append((message, details))
    w2.open_files([str(FIXTURE_PDF)])
    assert questions == ["فيه مراجعة قديمة للملف ده، تكمل منها؟"], questions
    assert w2.stack.currentWidget() is w2.review, "resumed without reading"
    r2 = w2.review
    assert r2.reviewed == {1, 2}
    assert r2.index == 2, "opens on the first page not reviewed yet"
    assert any(b.text.endswith("تجربة") for b in r2.document.pages[1].blocks)
    assert r2.page_list.item(0).data(Qt.ItemDataRole.UserRole) == "done"

    # ------------------------------------------------------------ save dialog
    out = tmp / "out folder"
    dlg = SaveDialog(r2.document, r2.reviewed, w2, has_next=True,
                     drives=lambda: [("E:\\", "KINGSTON")], confirm=lambda todo: True)
    dlg.resize(660, dlg.sizeHint().height())
    dlg.show()
    app.processEvents()
    assert dlg.selected_drive() == "E:\\", "a USB stick is preferred when one is plugged in"
    assert dlg.todo_banner.isVisible()
    shoot(dlg, "06_save_dialog.png")
    assert not missing_names(dlg), missing_names(dlg)
    dlg.choose_custom(out)
    assert dlg.destination() == out
    opts = dlg.options()
    assert opts.write_docx and opts.write_txt and opts.txt_encoding == "utf-8-sig"
    assert not dlg.enc_warning.isVisible()
    dlg.encoding_combo.setCurrentIndex(dlg.encoding_combo.findData("cp1256"))
    assert dlg.enc_warning.isVisible(), "Windows-1256 cannot hold Arabic-Indic digits"
    dlg.digit_radios["western"].setChecked(True)
    asked = []
    dlg.confirm = lambda todo: asked.append(todo) or True
    assert dlg.save()
    assert asked and len(asked[0]) == 56, "warned about pages not reviewed"
    written = dlg.written
    assert Path(written["docx"]).is_file() and Path(written["txt"]).is_file()
    assert Path(written["docx"]).parent == out
    assert written["lost"] >= 1, "the PUA glyph cannot be written in Windows-1256"
    assert dlg.lost_banner.isVisible()
    text = Path(written["txt"]).read_bytes().decode("cp1256")
    assert "صفحة 2" in text and "تجربة" in text
    assert "?" in text, "the broken glyph is replaced in Windows-1256"
    shoot(dlg, "07_save_result.png")
    stored = load_options()
    assert stored.txt_encoding == "cp1256" and stored.digits == "western"
    dlg.close()

    # the same dialog without problems: UTF-8, no warning about lost characters
    dlg = SaveDialog(r2.document, {p.number for p in r2.document.pages}, w2,
                     drives=lambda: [], confirm=lambda todo: False)
    assert not dlg.todo_banner.isVisible()
    assert dlg.encoding_combo.currentData() == "cp1256", "options remembered"
    dlg.encoding_combo.setCurrentIndex(dlg.encoding_combo.findData("utf-8-sig"))
    dlg.choose_custom(out)
    assert dlg.save()
    assert dlg.written["lost"] == 0 and not dlg.lost_banner.isVisible()
    raw = Path(dlg.written["txt"]).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    dlg.close()

    # ------------------------------------------------------------ dialogs
    report = ReportDialog(r2.document, w2)
    report.show()
    shoot(report, "08_report.png")
    report.close()
    err = ErrorDialog(w2, UNEXPECTED, "Traceback (most recent call last):\n  ...\n"
                      "RuntimeError: broken font table")
    err.show()
    err.toggle.setChecked(True)
    shoot(err, "09_error.png")
    assert not missing_names(err), missing_names(err)
    err.close()

    # ------------------------------------------------------------ Word file + queue
    from docx import Document as WordDocument
    word = tmp / "مذكرة.docx"
    WordDocument().save(str(word))
    w2.open_files([str(word), str(FIXTURE_PDF)])
    assert _wait(app, lambda: w2.stack.currentWidget() is w2.review
                 and w2.review.document.kind == "docx"), errors
    assert w2.queue == [os.path.normpath(str(FIXTURE_PDF))]
    assert w2.review.image_stack.currentWidget() is w2.review.no_image
    assert w2.review.next_file_btn.isVisible()
    shoot(w2, "10_review_word.png")
    questions.clear()
    w2.next_file()
    assert questions, "the PDF has a saved review"
    assert w2.review.document.kind == "pdf" and not w2.queue

    # ------------------------------------------------------------ errors from readers
    from nassbraille.convert import ConversionError

    def broken(path, progress=None):
        raise RuntimeError("broken font table")

    def refused(path, progress=None):
        raise ConversionError("الملف ده محمي بكلمة سر.")

    for reader, expect in ((broken, UNEXPECTED), (refused, "الملف ده محمي بكلمة سر.")):
        w3 = MainWindow(reader=reader)
        got = []
        w3.ask = lambda *a, **k: False
        w3.show_error = lambda message, details="": got.append((message, details))
        w3.open_files([str(FIXTURE_PDF)])
        assert _wait(app, lambda: bool(got)), "error reported"
        assert got[0][0] == expect
        if reader is broken:
            assert "RuntimeError" in got[0][1]
        assert w3.stack.currentWidget() is w3.start
        w3.close()

    # cancel while reading
    os.environ["NASSBRAILLE_FAKE_DELAY"] = "0.05"
    w4 = MainWindow()
    w4.ask = lambda *a, **k: False
    w4.open_files([str(FIXTURE_PDF)])
    assert _wait(app, lambda: w4.reading.bar.value() >= 2)
    w4.cancel_reading()
    assert _wait(app, lambda: w4.stack.currentWidget() is w4.start and not w4.is_reading())
    os.environ["NASSBRAILLE_FAKE_DELAY"] = "0"
    w4.close()

    # ------------------------------------------------------------ a failed file returns to the review
    def broken_reader(path, progress=None):
        raise RuntimeError("cannot read")

    before = (w2.review.document, w2.review.index)
    w2.reader = broken_reader
    w2.ask = lambda *a, **k: False            # read again instead of resuming
    failures = []
    w2.show_error = lambda message, details="": failures.append(message)
    w2.open_files([str(word)])
    assert _wait(app, lambda: bool(failures) and w2.stack.currentWidget() is w2.review)
    assert (w2.review.document, w2.review.index) == before, "back on the same page of the same file"

    # ------------------------------------------------------------ start screen again
    w2.go_home()
    assert w2.stack.currentWidget() is w2.start
    assert w2.start.recent.count() == 2, "the PDF and the Word file are in the recent list"
    shoot(w2, "11_start_recent.png")
    w2.close()
    app.processEvents()

    # ------------------------------------------------------------ drag and drop
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    from nassbraille.project import save_project

    w5 = MainWindow()
    w5.resize(1366, 768)
    w5.show()
    notes = []
    w5.ask = lambda *a, **k: True
    w5.inform = lambda title, text, warning=False: notes.append(text)
    other = tmp / "notes.txt"
    other.write_text("x", encoding="utf-8")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(FIXTURE_PDF)), QUrl.fromLocalFile(str(other))])
    enter = QDragEnterEvent(QPointF(100, 100), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    w5.dragEnterEvent(enter)
    assert enter.isAccepted() and w5.start.drop_zone.property("active") is True
    drop = QDropEvent(QPointF(100, 100), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    w5.dropEvent(drop)
    assert notes and "notes.txt" in notes[0], "the .txt file is refused politely"
    assert w5.start.drop_zone.property("active") is False
    assert _wait(app, lambda: w5.stack.currentWidget() is w5.review), "dropped PDF opened"

    # ------------------------------------------------------------ last page, all reviewed
    r5 = w5.review
    messages = []
    r5.message.connect(messages.append)
    r5.reviewed = {p.number for p in r5.document.pages} - {58}
    r5.go_to(57)
    r5.mark_done()
    assert r5.index == 57 and len(r5.reviewed) == 58
    assert any("كل الصفحات اتراجعت" in m for m in messages), messages
    assert r5.next_problem() is False or r5.index == 57

    # ------------------------------------------------------------ closing when saving fails
    def failing(document, reviewed):
        raise PermissionError("Access is denied")

    r5.saver = failing
    cursor = QTextCursor(r5.editor.document().firstBlock())
    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    r5.editor.setTextCursor(cursor)
    _type(r5.editor, "!")
    asked = []
    w5.ask = lambda title, text, yes="", no="": asked.append(text) or False
    w5.close()
    assert asked and "مقدرتش أحفظ المراجعة" in asked[0]
    assert w5.isVisible(), "stays open when the review could not be saved"
    QTest.keyClick(r5.editor, Qt.Key.Key_Backspace)
    r5.saver = save_project
    w5.ask = lambda *a, **k: True
    w5.close()
    assert not w5.isVisible()
    app.processEvents()
    print("UI smoke test passed. Screenshots:", SHOTS if shots else "(off)")


def test_ui_smoke():
    import pytest
    if not FIXTURE_PDF.exists():
        pytest.skip("local reference PDF not present (not distributed)")
    run(shots=True)


if __name__ == "__main__":
    run(shots="--no-shots" not in sys.argv)
