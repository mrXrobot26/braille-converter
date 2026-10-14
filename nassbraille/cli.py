"""Command line: convert files without the GUI.

python -m nassbraille.cli FILE [FILE ...] [-o OUTDIR] [--no-docx] [--no-txt]
       [--digits printed|western|arabic] [--pictures] [--no-markers]
       [--encoding utf-8-sig|utf-8|cp1256]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import OutputOptions
from .convert import ConversionError, read_document, write_outputs


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--device-test"]:
        from .devicetest import write_device_tests
        out = Path(argv[1]) if len(argv) > 1 else Path.cwd()
        for path in write_device_tests(out):
            print(path)
        return 0
    ap = argparse.ArgumentParser(prog="nassbraille")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", help="output folder (default: next to each file)")
    ap.add_argument("--no-docx", action="store_true")
    ap.add_argument("--no-txt", action="store_true")
    ap.add_argument("--digits", choices=("printed", "western", "arabic"), default="printed")
    ap.add_argument("--pictures", action="store_true", help="write «(صورة)» for removed pictures")
    ap.add_argument("--no-markers", action="store_true", help="no «صفحة N» lines")
    ap.add_argument("--encoding", default="utf-8-sig", choices=("utf-8-sig", "utf-8", "cp1256"))
    args = ap.parse_args(argv)

    opts = OutputOptions(write_docx=not args.no_docx, write_txt=not args.no_txt,
                         page_markers=not args.no_markers, digits=args.digits,
                         picture_markers=args.pictures, txt_encoding=args.encoding)
    failed = 0
    for name in args.files:
        path = Path(name)
        try:
            document = read_document(path)
        except ConversionError as exc:
            print(f"✗ {path.name}: {exc}")
            failed += 1
            continue
        result = write_outputs(document, Path(args.out) if args.out else path.parent, opts)
        words = sum(len(b.text.split()) for p in document.pages for b in p.blocks)
        print(f"✓ {path.name}: {len(document.pages)} صفحة، {words} كلمة")
        for kind in ("docx", "txt"):
            if result[kind]:
                print(f"   {result[kind]}")
        image_pages = document.report.get("image_pages") or []
        if image_pages:
            print(f"   صفحات صور (مفيش كلام يتقري): {', '.join(map(str, image_pages))}")
        flagged = [p.number for p in document.pages
                   if p.warnings or any(b.flags and b.flags != ["placed-box"] for b in p.blocks)]
        if flagged:
            print(f"   صفحات تستاهل مراجعة: {', '.join(map(str, flagged))}")
        if result["lost"]:
            print(f"   تنبيه: {result['lost']} حرف ماينفعش يتكتب بترميز {opts.txt_encoding}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
