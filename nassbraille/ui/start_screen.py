"""First screen: choose or drop files, or reopen a recent one."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from .common import isolate, named, recent_files, rtl


class StartScreen(QWidget):
    openRequested = Signal()
    filesChosen = Signal(list)

    def __init__(self, fake=False, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(780)
        card.setMinimumWidth(560)
        row.addWidget(card, 4)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(14)

        title = QLabel("نص برايل")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        named(title, "نص برايل")
        layout.addWidget(title)

        about = QLabel("البرنامج بيحوّل المذكرة (PDF أو Word) لملف Word وملف TXT فيهم الكلام بس "
                       "وبنفس الترتيب، عشان تتقري على جهاز البرايل من الفلاشة.")
        about.setObjectName("subtitle")
        about.setWordWrap(True)
        about.setAlignment(Qt.AlignmentFlag.AlignCenter)
        named(about, about.text())
        layout.addWidget(about)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setProperty("active", False)
        zone = QVBoxLayout(self.drop_zone)
        zone.setContentsMargins(20, 22, 20, 20)
        zone.setSpacing(10)
        self.open_btn = QPushButton("اختار ملف")
        self.open_btn.setObjectName("big")
        self.open_btn.setToolTip("اختار ملف PDF أو Word، أو كذا ملف مرة واحدة (Ctrl+O)")
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self.openRequested)
        named(self.open_btn, "اختار ملف", "افتح ملف PDF أو Word. اختصار Ctrl+O")
        zone.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = QLabel("أو اسحب الملفات من الفولدر وسيبها هنا. ينفع كذا ملف مرة واحدة.")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        zone.addWidget(hint)
        layout.addWidget(self.drop_zone)

        recent_title = QLabel("آخر ملفات اتفتحت:")
        recent_title.setObjectName("muted")
        layout.addWidget(recent_title)
        self.recent = QListWidget()
        self.recent.setMaximumHeight(170)
        self.recent.itemActivated.connect(self._recent_chosen)
        named(self.recent, "آخر ملفات اتفتحت", "دوس Enter أو دبل كليك على ملف عشان تفتحه")
        recent_title.setBuddy(self.recent)
        layout.addWidget(self.recent)
        self.no_recent = QLabel("لسه مفيش ملفات.")
        self.no_recent.setObjectName("muted")
        layout.addWidget(self.no_recent)

        if fake:
            note = QLabel("وضع التجربة: البرنامج بيستخدم قراية متسجلة (NASSBRAILLE_FAKE).")
            note.setObjectName("muted")
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(note)
        self.setTabOrder(self.open_btn, self.recent)
        self.refresh_recent()

    def refresh_recent(self):
        self.recent.clear()
        files = recent_files()
        for path in files:
            p = Path(path)
            folder = p.parent.name or str(p.parent)
            item = QListWidgetItem(rtl(f"{isolate(p.name)}   —   {isolate(folder)}"))
            item.setToolTip(str(p))
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{p.name} في فولدر {p.parent}")
            self.recent.addItem(item)
        self.recent.setVisible(bool(files))
        self.no_recent.setVisible(not files)
        if files:
            self.recent.setCurrentRow(0)

    def _recent_chosen(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.filesChosen.emit([path])

    def set_drag_active(self, active):
        self.drop_zone.setProperty("active", bool(active))
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
