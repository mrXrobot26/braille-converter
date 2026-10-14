"""نص برايل: convert Arabic study notes to text-only Word/TXT for a braille notetaker.

Usage:  python app.py [file ...]
        python app.py --cli FILE [FILE ...] [-o OUTDIR]   (no window; see nassbraille.cli)
        python app.py --cli --device-test OUTDIR         (test files for the device)
        NASSBRAILLE_FAKE=1 python app.py      (GUI work without the real readers)

Unexpected errors are appended to %LOCALAPPDATA%\\NassBraille\\crash.log.
"""
import datetime
import os
import sys
import traceback
from pathlib import Path


def crash_log(exc_type, exc, tb):
    folder = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "NassBraille"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "crash.log"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {sys.argv[1:]} ===\n")
        traceback.print_exception(exc_type, exc, tb, file=fh)
    return path


def _hook(exc_type, exc, tb):
    crash_log(exc_type, exc, tb)
    sys.__excepthook__(exc_type, exc, tb)


if __name__ == "__main__":
    sys.excepthook = _hook
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        if sys.stdout is None:          # windowed build has no console
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        try:
            from nassbraille.cli import main as cli_main
            code = cli_main(sys.argv[2:])
        except SystemExit:
            raise
        except BaseException:
            crash_log(*sys.exc_info())
            code = 2
        sys.exit(code)
    from nassbraille.ui import main
    sys.exit(main())
