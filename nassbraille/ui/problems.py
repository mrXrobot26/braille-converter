"""What the review screen highlights. Pure functions, no Qt.

Three kinds of spots:
  bad     characters that cannot be right: Private Use Area glyphs, U+FFFD and
          non-Arabic letters inside an Arabic word (red)
  low     a line the reader was unsure of: confidence < 0.8 or a flag such as
          "low-font" / "unknown-glyph" (orange)
  placed  a box whose position in the reading order was guessed (yellow)
"""
from __future__ import annotations

import re
import unicodedata

LOW_CONFIDENCE = 0.8
LOW_FLAGS = frozenset({"low-font", "unknown-glyph", "suspect-words"})
PLACED_FLAG = "placed-box"
CONTENT_KINDS = ("h1", "h2", "h3", "h4", "para", "box", "caption")


def is_impossible(ch):
    cp = ord(ch)
    return 0xE000 <= cp <= 0xF8FF or cp == 0xFFFD


def _arabic_script(cp):
    return (0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x0870 <= cp <= 0x08FF
            or 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF)


def _wordish(ch):
    """Letters, combining marks (harakat) and broken glyphs make up a word."""
    return unicodedata.category(ch)[0] in "LM" or is_impossible(ch)


def _letter_script(ch):
    """'ar' for an Arabic letter, 'other' for any other letter, None otherwise."""
    if unicodedata.category(ch)[0] != "L":
        return None
    return "ar" if _arabic_script(ord(ch)) else "other"


# Fast pre-check: plain Arabic text, digits, spaces and punctuation are never bad,
# so only lines with some other character get the slower scan below.
_SAFE_RANGES = [(0x09, 0x0D), (0x20, 0x40), (0x5B, 0x60), (0x7B, 0x7E), (0xA0, 0xBF),
                (0x0600, 0x06FF), (0x0750, 0x077F), (0x0870, 0x08FF), (0x2000, 0x206F),
                (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)]
_SUSPECT = re.compile("[^" + "".join(re.escape(chr(a)) + "-" + re.escape(chr(b))
                                     for a, b in _SAFE_RANGES) + "]")


def bad_char_positions(text):
    """Sorted indexes of characters in `text` that cannot be right."""
    if not _SUSPECT.search(text):
        return []
    bad = {i for i, ch in enumerate(text) if is_impossible(ch)}
    i, n = 0, len(text)
    while i < n:
        if not _wordish(text[i]):
            i += 1
            continue
        j, scripts = i, set()
        while j < n and _wordish(text[j]):
            script = _letter_script(text[j])
            if script:
                scripts.add(script)
            j += 1
        if scripts == {"ar", "other"}:
            bad.update(k for k in range(i, j) if _letter_script(text[k]) == "other")
        i = j
    return sorted(bad)


def spans(positions):
    """[3, 4, 5, 9] -> [(3, 3), (9, 1)] as (start, length)."""
    out = []
    for pos in positions:
        if out and out[-1][0] + out[-1][1] == pos:
            out[-1] = (out[-1][0], out[-1][1] + 1)
        else:
            out.append((pos, 1))
    return out


def bad_spans(text):
    return spans(bad_char_positions(text))


def line_level(info):
    """'low', 'placed' or None for anything with .confidence and .flags."""
    if info is None:
        return None
    flags = set(getattr(info, "flags", None) or ())
    confidence = getattr(info, "confidence", 1.0)
    if confidence is None:
        confidence = 1.0
    if confidence < LOW_CONFIDENCE or flags & LOW_FLAGS:
        return "low"
    if PLACED_FLAG in flags:
        return "placed"
    return None


def line_spots(text, info, previous_level=None):
    """Places F8 stops at, as (start, length); length 0 = the whole line.
    A coloured line right under a line of the same colour is not a new stop
    (a yellow box of five lines is one thing to check)."""
    out = []
    level = line_level(info) if text.strip() else None
    if level and level != previous_level:
        out.append((0, 0))
    out.extend(bad_spans(text))
    return out


def spots_in_lines(lines):
    """[(line number, start, length)] for [(text, info)] in page order."""
    out, previous = [], None
    for number, (text, info) in enumerate(lines):
        out.extend((number, start, length) for start, length in line_spots(text, info, previous))
        previous = line_level(info) if text.strip() else None
    return out


def block_needs_attention(block):
    """⚠ in the page list: unsure lines and impossible characters (a guessed
    box position alone is only highlighted, it does not mark the page)."""
    return line_level(block) == "low" or bool(bad_char_positions(block.text))


def page_needs_attention(page):
    return bool(page.warnings) or any(block_needs_attention(b) for b in page.blocks)


def page_has_text(page):
    return any(b.kind in CONTENT_KINDS and b.text.strip() for b in page.blocks)
