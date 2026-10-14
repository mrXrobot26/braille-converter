"""Small shared GUI helpers: Arabic digits, settings, simple dialogs."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

APP_NAME = "نص برايل"
AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
MAX_RECENT = 10


def ar(value):
    """Number (or text) with Arabic-Indic digits, as people read them here."""
    return str(value).translate(AR_DIGITS)


def rtl(text):
    """Start with a right-to-left mark so Latin-only text (a file name) stays on the right."""
    return chr(0x200F) + str(text)   # right-to-left mark


def isolate(text):
    """Show text in its own direction inside other text (first-strong isolate)."""
    return chr(0x2068) + str(text) + chr(0x2069)


def ar_list(numbers, limit=15):
    numbers = list(numbers)
    text = "، ".join(ar(n) for n in numbers[:limit])
    if len(numbers) > limit:
        text += "، …"
    return text


# ---------------------------------------------------------------- settings

def settings():
    """App settings; NASSBRAILLE_SETTINGS=<file.ini> keeps tests out of the registry."""
    path = os.environ.get("NASSBRAILLE_SETTINGS")
    if path:
        return QSettings(path, QSettings.Format.IniFormat)
    return QSettings("NassBraille", "NassBraille")


def get_json(key, default):
    raw = settings().value(key)
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def set_json(key, value):
    s = settings()
    s.setValue(key, json.dumps(value, ensure_ascii=False))
    s.sync()


def recent_files():
    items = get_json("recent", [])
    if not isinstance(items, list):
        return []
    return [p for p in items if isinstance(p, str) and Path(p).exists()]


def add_recent(path):
    path = str(Path(path).resolve())
    items = [p for p in get_json("recent", []) if isinstance(p, str)]
    items = [path] + [p for p in items if os.path.normcase(p) != os.path.normcase(path)]
    set_json("recent", items[:MAX_RECENT])


# ------------------------------------------------------------ accessibility

def named(widget, name, description=None):
    """Give a control the name a screen reader says."""
    widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
    return widget


# ------------------------------------------------------------------ dialogs

def _box(parent, icon, title, text):
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    return box


def ask(parent, title, text, yes="أيوه", no="لأ"):
    """Yes/no question with Arabic buttons. Returns True for yes."""
    box = _box(parent, QMessageBox.Icon.Question, title, text)
    yes_btn = box.addButton(yes, QMessageBox.ButtonRole.YesRole)
    no_btn = box.addButton(no, QMessageBox.ButtonRole.NoRole)
    named(yes_btn, yes)
    named(no_btn, no)
    box.setDefaultButton(yes_btn)
    box.setEscapeButton(no_btn)
    box.exec()
    return box.clickedButton() is yes_btn


def inform(parent, title, text, warning=False):
    icon = QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information
    box = _box(parent, icon, title, text)
    ok = box.addButton("تمام", QMessageBox.ButtonRole.AcceptRole)
    named(ok, "تمام")
    box.setDefaultButton(ok)
    box.exec()


class ErrorDialog(QDialog):
    """A friendly message, with the technical details folded away."""

    def __init__(self, parent, message, details="", title="حصلت مشكلة"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        label = QLabel(message)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setObjectName("errorMessage")
        named(label, message)
        layout.addWidget(label)

        self.details = QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.details.setMinimumHeight(180)
        self.details.setVisible(False)
        named(self.details, "التفاصيل الفنية")
        layout.addWidget(self.details)

        row = QHBoxLayout()
        self.toggle = QPushButton("اعرض التفاصيل")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._toggle)
        named(self.toggle, "اعرض التفاصيل الفنية")
        self.copy_btn = QPushButton("انسخ التفاصيل")
        self.copy_btn.clicked.connect(self._copy)
        named(self.copy_btn, "انسخ التفاصيل")
        ok = QPushButton("تمام")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        named(ok, "تمام")
        if details:
            row.addWidget(self.toggle)
            row.addWidget(self.copy_btn)
        row.addStretch(1)
        row.addWidget(ok)
        layout.addLayout(row)

    def _toggle(self, on):
        self.details.setVisible(on)
        self.toggle.setText("خبّي التفاصيل" if on else "اعرض التفاصيل")
        self.adjustSize()

    def _copy(self):
        QGuiApplication.clipboard().setText(self.details.toPlainText())
        self.copy_btn.setText("اتنسخت")
