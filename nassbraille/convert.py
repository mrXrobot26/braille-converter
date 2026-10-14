"""Entry points used by the GUI and the CLI.

read_document(path) -> Document      (PDF / DOCX / DOC)
write_outputs(document, out_dir, opts) -> {"docx": Path|None, "txt": Path|None, "lost": int}
"""
from __future__ import annotations

from pathlib import Path

from .config import OutputOptions
from .writers.docx_writer import write_docx
from .writers.txt_writer import write_txt

SUPPORTED = (".pdf", ".docx", ".docm", ".dotx", ".dotm", ".doc", ".rtf", ".odt")


class ConversionError(Exception):
    """Raised with a user-facing Arabic message."""


def read_document(path, progress=None):
    """progress(done, total, message) is called from the reading thread."""
    path = Path(path)
    if not path.exists():
        raise ConversionError(f"الملف مش موجود: {path}")
    ext = path.suffix.lower()
    if ext == ".pdf":
        from .pdf.reader import read_pdf
        return read_pdf(path, progress=progress)
    if ext in (".docx", ".docm", ".dotx", ".dotm"):
        from .docx_in.reader import read_docx
        return read_docx(path, progress=progress)
    if ext in (".doc", ".rtf", ".odt"):
        from .doc_legacy import convert_to_docx
        from .docx_in.reader import read_docx
        tmp = convert_to_docx(path)
        document = read_docx(tmp, progress=progress)
        document.source = str(path)
        return document
    raise ConversionError("نوع الملف ده مش مدعوم. البرنامج بيقبل PDF وWord (docx/doc).")


def output_stem(document):
    return Path(document.source).stem + " - نسخة نصية"


def write_outputs(document, out_dir, opts=None):
    opts = opts or OutputOptions()
    out_dir = Path(out_dir)
    result = {"docx": None, "txt": None, "lost": 0}
    stem = output_stem(document)
    if opts.write_docx:
        result["docx"] = write_docx(document, out_dir / (stem + ".docx"), opts)
    if opts.write_txt:
        path = out_dir / (stem + ".txt")
        result["lost"] = write_txt(document, path, opts)
        result["txt"] = path
    return result
