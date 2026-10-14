"""Output writers shared helpers."""
from __future__ import annotations

from ..textnorm import TO_ARABIC, TO_WESTERN, apply_digits, clean


def wants_markers(document, opts):
    """Page markers make sense for PDFs, or Word files with known page breaks."""
    return opts.page_markers and (document.kind == "pdf" or len(document.pages) > 1)


def marker_text(number, opts):
    digits = str(number)
    if opts.digits != "western":
        digits = digits.translate(TO_ARABIC)
    return "صفحة " + digits


def output_blocks(page, opts):
    """Blocks to write for a page, with final spacing and digit rules applied."""
    for block in page.blocks:
        if block.kind == "picture" and not opts.picture_markers:
            continue
        text = apply_digits(clean(block.text), opts.digits)
        if text:
            yield block, text


__all__ = ["wants_markers", "marker_text", "output_blocks", "TO_WESTERN"]
