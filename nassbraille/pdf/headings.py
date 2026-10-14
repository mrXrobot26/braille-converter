"""Find headings by style when the PDF has no heading tags.

A style is (font, size). The body style is the one with the most words. A
style counts as a heading style when most of its paragraphs are short lines
without sentence punctuation (questions «س:» and list labels excluded). Only
short paragraphs of a heading style become headings; levels follow size.
"""
from __future__ import annotations

import collections
import re

QUESTION = re.compile(r"^\s*(س|ج)\s*[0-9٠-٩]*\s*[/:،.)\-]|^\s*(س|ج)[0-9٠-٩]")
END_PUNCT = (".", "؟", "!", "،", "؛", "…", "?", ",", ";")


def _style(block, fonts):
    counts = getattr(block, "fonts", None)
    if not counts:
        return None
    key, n = max(counts.items(), key=lambda kv: kv[1])
    if n < 0.8 * sum(counts.values()):
        return None
    name = fonts[key].name if isinstance(key, int) else str(key)
    return (name, round(getattr(block, "size", 0.0) * 2) / 2)


def _lines(block):
    if hasattr(block, "lines"):
        return block.lines
    size = getattr(block, "size", 0.0) or 1.0
    if not block.bboxes:
        return 1
    h = block.bboxes[0][3] - block.bboxes[0][1]
    return max(1, round(h / (1.35 * size)))


def _short(block):
    text = block.text.strip()
    return (len(text.split()) <= 12 and not text.endswith(END_PUNCT)
            and _lines(block) <= 2 and not QUESTION.match(text))


def mark_headings(pages, fonts):
    """Returns the number of blocks turned into headings."""
    if any(b.kind in ("h1", "h2", "h3", "h4") for p in pages for b in p.blocks):
        return 0                          # the PDF has heading tags: trust them
    by_style = collections.defaultdict(list)
    for p in pages:
        for b in p.blocks:
            if b.kind == "para":
                s = _style(b, fonts)
                if s:
                    by_style[s].append(b)
    if not by_style:
        return 0
    body = max(by_style.items(), key=lambda kv: sum(len(b.text.split()) for b in kv[1]))[0]
    marked = 0
    for style, blocks in by_style.items():
        if style == body or (style[0] == body[0] and style[1] < body[1] + 1.5):
            continue
        shorts = [b for b in blocks if _short(b)]
        # questions share styles with headings in many notes; judge without them
        others = [b for b in blocks if not QUESTION.match(b.text.strip())]
        if len(shorts) < 2 or len(shorts) < 0.6 * len(others):
            continue
        level = "h3" if style[1] >= body[1] + 3.5 else "h4"
        for b in shorts:
            b.kind = level
            marked += 1
    return marked
