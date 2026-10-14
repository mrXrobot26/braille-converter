"""Desktop GUI (PySide6, Arabic, right to left).

python app.py [file ...]          start the program (optionally opening files)
NASSBRAILLE_FAKE=1                use the fake reader in dev_fake.py
"""


def main(argv=None):
    from .app import main as _main
    return _main(argv)
