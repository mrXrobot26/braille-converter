"""Read a PDF into the Document model.

Pass 1 records every page through the device and registers fonts. Then each
font gets its decoder (decide.py), the numeral style is inferred, and pass 2
assembles blocks: struct-tree order for tagged pages, geometry otherwise.
"""
from __future__ import annotations

import pymupdf

from ..convert import ConversionError
from ..model import PICTURE_MARKER, Block, Document, Page
from ..textnorm import clean
from .decide import decide_fonts, numeral_mode, violations, words_of
from .device import record_page
from .fonts import FontRegistry
from .geometric import geometric_blocks, page_rects, repeated_bands
from .headings import mark_headings
from .structtree import StructResolver, inject_rolemap, is_marked, struct_root
from .tagged import assemble, page_atoms

IMAGE_PAGE_NOTE = "الصفحة دي صورة كاملة: مفيش كلام يتقري منها (غلاف أو صورة)."
TEXT_IN_PICTURE_NOTE = "فيه صور كبيرة في الصفحة دي، ممكن يكون جواها كلام مش هيطلع."


def _tag_coverage(rec):
    glyphs = [g for g in rec.glyphs if g.vis >= 0.5 and not g.invisible and g.tu.strip()]
    body = [g for g in glyphs if 0.08 * rec.height < g.y < 0.92 * rec.height]
    if not body:
        return 1.0 if rec.metas else 0.0
    return sum(1 for g in body if g.path) / len(body)


def _page_warnings(rec, blocks):
    words = sum(len(b.text.split()) for b in blocks if b.kind != "picture")
    page_area = rec.width * rec.height
    pics = [p for p in rec.pictures if p.vis >= 0.5 and not p.mask]
    largest = max((max(0, p.bbox[2] - p.bbox[0]) * max(0, p.bbox[3] - p.bbox[1])
                   for p in pics), default=0.0)
    warnings, image_page = [], False
    if largest >= 0.85 * page_area and words <= 5:
        warnings.append(IMAGE_PAGE_NOTE)
        image_page = True
    else:
        big = [p for p in pics if p.meta is None and
               (p.bbox[2] - p.bbox[0]) * (p.bbox[3] - p.bbox[1]) >= 0.04 * page_area]
        if big:
            warnings.append(TEXT_IN_PICTURE_NOTE)
    return warnings, image_page


def _flag_suspects(blocks, fonts):
    """Mark blocks the helper should look at in the review screen."""
    for b in blocks:
        bad = [w for w in words_of(clean(b.text)) if violations(w)]
        if bad:
            b.flags.append("suspect-words")
            b.confidence = min(b.confidence, 0.7)
        for key in getattr(b, "fonts", {}) or {}:
            if isinstance(key, int):
                info = fonts[key]
                if not info.scores or info.scores.get("agreement", 0) >= 0.98:
                    continue          # both readings agree: nothing to doubt
                if info.scores.get("bad_words", 0) > 0.05:   # garbled text is full of impossible words
                    if "low-font" not in b.flags:
                        b.flags.append("low-font")
                    b.confidence = min(b.confidence, 0.75)


def read_pdf(path, progress=None, use_tags=True):
    """use_tags=False ignores the struct tree (for testing the geometric path)."""
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise ConversionError(f"الملف ده مش PDF سليم أو مش بيتفتح: {exc}") from exc
    if doc.needs_pass:
        raise ConversionError("الملف محمي بكلمة سر. افتحه واحفظه من غير كلمة سر الأول.")
    total = doc.page_count
    if not use_tags and struct_root(doc) is not None:
        doc.xref_set_key(doc.pdf_catalog(), "StructTreeRoot", "null")
        doc.xref_set_key(doc.pdf_catalog(), "MarkInfo", "null")
    tagged = struct_root(doc) is not None
    resolver = None
    if tagged:
        inject_rolemap(doc)
        resolver = StructResolver(doc)
    fonts = FontRegistry()
    records = []
    for i, page in enumerate(doc):
        rec = record_page(page, i + 1, fonts)
        rec.rects = page_rects(page, rec)
        records.append(rec)
        if progress:
            progress(i + 1, 2 * total, "بقرا الصفحات")
    font_report = decide_fonts(records, fonts)
    numerals, ai, we = numeral_mode(records, fonts)

    use_tagged = {rec.number: tagged and _tag_coverage(rec) >= 0.95 for rec in records}
    drop = repeated_bands(records, fonts) if not all(use_tagged.values()) else None
    pages = []
    image_pages, methods = [], {"tagged": 0, "geometric": 0}
    for rec in records:
        if use_tagged[rec.number]:
            blocks = assemble(page_atoms(rec, fonts, numerals, resolver))
            methods["tagged"] += 1
        else:
            blocks = geometric_blocks(rec, fonts, rec.rects, drop)
            methods["geometric"] += 1
        warnings, image_page = _page_warnings(rec, blocks)
        if image_page:
            image_pages.append(rec.number)
            if not blocks:
                blocks = [Block("picture", PICTURE_MARKER, [(0, 0, rec.width, rec.height)])]
        _flag_suspects(blocks, fonts)
        pages.append(Page(rec.number, blocks, warnings, (rec.width, rec.height)))
        if progress:
            progress(total + rec.number, 2 * total, "بجمع الكلام بالترتيب")

    headings = mark_headings(pages, fonts)
    report = {
        "pages": total,
        "headings_by_style": headings,
        "tagged": tagged and is_marked(doc),
        "methods": methods,
        "image_pages": image_pages,
        "numerals": numerals,
        "fonts": font_report,
    }
    return Document(str(path), "pdf", pages, report)
