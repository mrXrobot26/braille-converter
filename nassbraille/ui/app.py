"""Start the GUI: QApplication set up for Arabic, right to left."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTimer, QTranslator
from PySide6.QtWidgets import QApplication

from .common import APP_NAME
from .style import app_icon, apply_style


def prepare_environment():
    """The offscreen platform (tests, screenshots) finds no fonts on Windows
    unless pointed at the Windows font folder."""
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    if platform.startswith("offscreen") and sys.platform == "win32" \
            and not os.environ.get("QT_QPA_FONTDIR"):
        os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                                    "Fonts")


def set_windows_app_id():
    """Own taskbar icon instead of Python's."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NassBraille.App")
        except Exception:
            pass


def setup_application(app):
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("NassBraille")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.Arabic, QLocale.Country.Egypt), "qtbase", "_",
                       folder):
        app.installTranslator(translator)
        app._nassbraille_translator = translator   # keep it alive
    apply_style(app)
    app.setWindowIcon(app_icon())
    return app


def create_application(argv=None):
    prepare_environment()
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(sys.argv if argv is None else argv))
    return setup_application(app)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    set_windows_app_id()
    app = create_application(argv)
    from .common import settings
    from .main_window import MainWindow
    window = MainWindow()
    if settings().value("window/geometry") is None:
        window.showMaximized()      # first run: use the whole screen
    else:
        window.show()               # restoreGeometry() already applied size/state
    files = [a for a in app.arguments()[1:] if not a.startswith("-")]
    if files:
        QTimer.singleShot(0, lambda: window.open_files(files))
    return app.exec()
