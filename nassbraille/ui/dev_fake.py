"""Fake reader for working on the GUI before the real readers exist.

Turned on with the environment variable NASSBRAILLE_FAKE=1. Any PDF that is
opened gives the verified Saifi transcription (tests/fixtures/saifi/gold) with
source = tests/fixtures/saifi/original.pdf, so the page images work. Blocks get
plausible bounding boxes stacked down the page, and a few pages get problems
on purpose (low confidence, flags, broken characters, page warnings) so every
highlight can be tried. NASSBRAILLE_FAKE=clean leaves the text exactly as the
gold files. A .docx/.doc gives a short Word-style document (no page images).

NASSBRAILLE_FAKE_DELAY=<seconds per page> slows the fake reading (default 0.02).
"""
from __future__ import annotations

import math
import os
import random
import time
from pathlib import Path

from ..model import Document, Page, markup_to_blocks

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "saifi"
FIXTURE_PDF = FIXTURE / "original.pdf"
GOLD = FIXTURE / "gold"
A4 = (595.32, 841.92)

WORD_SUFFIXES = (".docx", ".doc", ".rtf", ".odt")

# deliberate problems so that the review highlights can be exercised
PAGE_WARNINGS = {
    1: ["الصفحة دي صورة بس، الكلام اتقرا من الصورة. قارن كل كلمة."],
    3: ["فيه خط مش معروف في الصفحة دي، راجع الحروف كويس."],
    7: ["فيه برواز اتحط في مكان متخمّن، اتأكد من ترتيب الكلام."],
}
BROKEN = {
    # page: (block index, kind of damage)
    2: (3, "pua"),
    3: (2, "fffd"),
    4: (4, "latin"),
}
PLACED_BOX_PAGES = (2, 5, 7)
LOW_CONFIDENCE_PAGES = (2, 4, 6, 9, 13, 21, 30, 44)
AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def enabled():
    return os.environ.get("NASSBRAILLE_FAKE", "").strip().lower() not in ("", "0", "false", "no")


def _clean_mode():
    return os.environ.get("NASSBRAILLE_FAKE", "").strip().lower() == "clean"


def _delay():
    try:
        return max(0.0, float(os.environ.get("NASSBRAILLE_FAKE_DELAY", "0.02")))
    except ValueError:
        return 0.02


def _gold_pages():
    return sorted(GOLD.glob("p*.txt"))


def _page_sizes(count):
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - older PyMuPDF
        import fitz as pymupdf
    try:
        with pymupdf.open(str(FIXTURE_PDF)) as pdf:
            return [(pdf[i].rect.width, pdf[i].rect.height) if i < pdf.page_count else A4
                    for i in range(count)]
    except Exception:
        return [A4] * count


# chars per printed line and line height (points) by block kind
_SHAPE = {"h1": (28, 30), "h2": (38, 24), "h3": (52, 20), "h4": (60, 18),
          "box": (78, 16), "caption": (64, 15), "picture": (20, 15)}


def _layout(blocks, width, height):
    """Plausible boxes, stacked down the page in reading order (right aligned)."""
    left, right, top, bottom = 42.0, width - 42.0, 70.0, height - 64.0
    full = right - left
    shapes = []
    for block in blocks:
        cpl, lh = _SHAPE.get(block.kind, (84, 16))
        lines = max(1, math.ceil(len(block.text) / cpl))
        shapes.append((cpl, lh, lines))
    gap = 7.0
    need = sum(lh * lines + 4 for _, lh, lines in shapes) + gap * max(0, len(blocks) - 1)
    scale = min(1.0, (bottom - top) / need) if need else 1.0
    y = top
    for block, (cpl, lh, lines) in zip(blocks, shapes):
        h = (lh * lines + 4) * scale
        w = full if lines > 1 else max(40.0, full * min(1.0, len(block.text) / cpl))
        if block.kind == "box":
            x1, w = right - 16, min(w, full - 32)
        elif block.kind in ("h1", "h2"):
            x1 = left + (full + w) / 2
        else:
            x1 = right
        x0 = x1 - w
        if lines >= 3:  # a long paragraph broken over two pieces
            mid = y + h / 2
            block.bboxes = [(round(x0, 1), round(y, 1), round(x1, 1), round(mid - 1, 1)),
                            (round(x0, 1), round(mid + 1, 1), round(x1, 1), round(y + h, 1))]
        else:
            block.bboxes = [(round(x0, 1), round(y, 1), round(x1, 1), round(y + h, 1))]
        y += h + gap * scale


def _damage(text, how):
    """Imitate a broken extraction inside the middle of an Arabic word."""
    for i in range(len(text) // 3, len(text) - 1):
        if "ء" <= text[i] <= "ي" and "ء" <= text[i - 1] <= "ي":
            if how == "pua":
                return text[:i] + chr(0xE02A) + text[i + 1:]   # Private Use Area glyph
            if how == "fffd":
                return text[:i] + chr(0xFFFD) + text[i + 1:]   # replacement character
            return text[:i] + "J" + text[i + 1:]
    return text


def _decorate(number, blocks, rng):
    """Add low-confidence lines, flags and broken characters for testing."""
    if _clean_mode():
        return
    if number in LOW_CONFIDENCE_PAGES and blocks:
        for block in rng.sample(blocks, min(2, len(blocks))):
            block.confidence = round(rng.uniform(0.45, 0.78), 2)
            block.flags.append("low-font")
    if number in BROKEN:
        index, how = BROKEN[number]
        if index < len(blocks):
            block = blocks[index]
            block.text = _damage(block.text, how)
            block.confidence = min(block.confidence, 0.6)
            if "unknown-glyph" not in block.flags:
                block.flags.append("unknown-glyph")
    if number in PLACED_BOX_PAGES:
        for block in blocks:
            if block.kind == "box":
                block.flags.append("placed-box")
                break


def read_document(path, progress=None):
    """Same contract as convert.read_document(path, progress)."""
    path = Path(path)
    if path.suffix.lower() in WORD_SUFFIXES:
        return _fake_word(path, progress)
    files = _gold_pages()
    total = len(files)
    sizes = _page_sizes(total)
    delay = _delay()
    pages = []
    low = 0
    for i, file in enumerate(files, 1):
        if progress:
            progress(i - 1, total, f"بقرا صفحة {i} من {total}".translate(AR_DIGITS))
        blocks = markup_to_blocks(file.read_text(encoding="utf-8"))
        w, h = sizes[i - 1]
        _layout(blocks, w, h)
        _decorate(i, blocks, random.Random(i * 7919))
        low += sum(1 for b in blocks if b.confidence < 0.8)
        warnings = [] if _clean_mode() else list(PAGE_WARNINGS.get(i, []))
        pages.append(Page(i, blocks, warnings, (w, h)))
        if delay:
            time.sleep(delay)
    if progress:
        progress(total, total, "خلصت القراية")
    report = {
        "pages": total,
        "image_only_pages": [1],
        "pages_with_warnings": [p.number for p in pages if p.warnings],
        "low_confidence_blocks": low,
        "reader": "fake (NASSBRAILLE_FAKE)",
        "broken_fonts": ["AdvertisingBold", "AF_Hijaz"],
    }
    return Document(str(FIXTURE_PDF), "pdf", pages, report)


def _fake_word(path, progress):
    files = _gold_pages()[1:4]
    pages = []
    for i, file in enumerate(files, 1):
        if progress:
            progress(i - 1, len(files), f"بقرا الجزء {i}".translate(AR_DIGITS))
        pages.append(Page(i, markup_to_blocks(file.read_text(encoding="utf-8"))))
        time.sleep(_delay())
    return Document(str(path), "docx", pages, {"pages": len(pages), "reader": "fake (Word)"})
