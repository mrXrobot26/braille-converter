"""Turn positioned glyph clusters into logical text.

Glyphs are drawn in visual order. For right-to-left text we sort them by
their centre, right to left, then put back the left-to-right islands
(numbers, Latin words) in their own order. A cluster's own text (a ligature's
letters) is never reordered: ToUnicode keeps it logical already.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "«": "»", "»": "«",
          "<": ">", ">": "<", "‹": "›", "›": "‹"}
ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ]")


@dataclass
class Token:
    text: str
    x0: float             # advance box: pen position .. pen + advance
    x1: float
    y: float
    size: float
    space_em: float
    from_font: bool       # text is the glyph's drawn identity (may need mirroring)
    is_space: bool
    is_mark: bool
    seq: int
    ink_cx: float = 0.0   # centre of the inked box (marks attach by it)

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2


def _bidi_class(text):
    for ch in text:
        c = unicodedata.bidirectional(ch)
        if c in ("L", "R", "AL", "EN", "AN"):
            return c
    for ch in text:
        c = unicodedata.bidirectional(ch)
        if c:
            return c
    return "ON"


def is_rtl_text(tokens):
    """Right-to-left unless the text has no Arabic at all: in Arabic notes a
    line with a long English name is still an Arabic paragraph."""
    ar = sum(len(ARABIC_RE.findall(t.text)) for t in tokens)
    la = sum(len(LATIN_RE.findall(t.text)) for t in tokens)
    return ar > 0 or la == 0


def split_lines(tokens):
    """Group tokens into lines (top to bottom); marks attach to their base."""
    bases = sorted((t for t in tokens if not t.is_mark), key=lambda t: (t.y, -t.cx))
    lines = []
    for t in bases:
        tol = 0.3 * t.size
        for line in lines:
            if abs(line[0].y - t.y) <= max(tol, 0.3 * line[0].size):
                line.append(t)
                break
        else:
            lines.append([t])
    lines.sort(key=lambda line: sum(t.y for t in line) / len(line))
    marks = [t for t in tokens if t.is_mark]
    attached = {}
    for m in marks:
        best, best_d = None, None
        for li, line in enumerate(lines):
            for bi, b in enumerate(line):
                if b.is_space:
                    continue
                dy = abs(b.y - m.y)
                if dy > 1.2 * max(b.size, m.size):
                    continue
                inside = b.x0 - 0.5 <= m.ink_cx <= b.x1 + 0.5
                d = (0 if inside else abs(m.ink_cx - b.cx)) + dy * 0.01
                if best_d is None or d < best_d:
                    best, best_d = (li, id(b)), d
        if best is not None:
            attached.setdefault(best, []).append(m)
    return lines, attached


def _line_text(line, marks_for, rtl):
    line = sorted(line, key=lambda t: -t.cx if rtl else t.cx)
    seq = []          # [(text, cls, from_font)]
    prev = None
    pending_space = False
    for t in line:
        if t.is_space:
            if prev is None and not seq:
                seq.append((" ", "WS", False))      # leading space: keep for joins
            pending_space = True
            continue
        if prev is not None:
            gap = (prev.x0 - t.x1) if rtl else (t.x0 - prev.x1)
            sp = max(prev.space_em * prev.size, t.space_em * t.size, 0.1)
            if (pending_space and gap >= 0.3 * sp) or (not pending_space and gap >= 1.2 * sp):
                seq.append((" ", "WS", False))
        text = t.text + "".join(m.text for m in marks_for(t))
        seq.append((text, _bidi_class(t.text), t.from_font))
        prev = t
        pending_space = False
    if pending_space and prev is not None:
        seq.append((" ", "WS", False))              # trailing space: keep for joins
    if rtl:
        seq = _restore_ltr_islands(seq)
    return "".join(text for text, _, _ in seq)


def _restore_ltr_islands(seq):
    """seq is in right-to-left visual order; reverse every LTR island."""
    n = len(seq)
    cls = [c for _, c, _ in seq]
    # weak types: marks follow their neighbour, numbers' separators join numbers
    for i in range(n):
        if cls[i] == "NSM":
            cls[i] = cls[i - 1] if i else "R"
    num = {"EN", "AN"}
    for i in range(1, n - 1):
        if cls[i] in ("ES", "CS") and cls[i - 1] in num and cls[i + 1] in num:
            cls[i] = cls[i - 1]
    for i in range(n):
        if cls[i] == "ET" and ((i and cls[i - 1] in num) or (i + 1 < n and cls[i + 1] in num)):
            cls[i] = "EN"
    ltr = {"L", "EN", "AN"}
    is_ltr = [c in ltr for c in cls]
    # neutrals between two LTR members join when at least one side is a letter
    i = 0
    while i < n:
        if is_ltr[i]:
            i += 1
            continue
        j = i
        while j < n and not is_ltr[j] and cls[j] in ("WS", "ON", "CS", "ES", "ET", "BN", "S"):
            j += 1
        if 0 < i and j < n and is_ltr[i - 1] and is_ltr[j] and j > i:
            if cls[i - 1] == "L" or cls[j] == "L":
                for k in range(i, j):
                    is_ltr[k] = True
        i = max(j, i + 1)
    out = []
    i = 0
    while i < n:
        if is_ltr[i]:
            j = i
            while j < n and is_ltr[j]:
                j += 1
            out.extend(reversed(seq[i:j]))
            i = j
        else:
            text, c, from_font = seq[i]
            if from_font and text in MIRROR:
                text = MIRROR[text]
            out.append((text, c, from_font))
            i += 1
    return out


def tokens_text(tokens, rtl=None):
    """Logical text of tokens that may span several lines (joined by a space)."""
    if not tokens:
        return ""
    if rtl is None:
        rtl = is_rtl_text(tokens)
    lines, attached = split_lines(tokens)

    def marks_for_line(li):
        return lambda t: attached.get((li, id(t)), [])

    texts = [t for t in (_line_text(line, marks_for_line(li), rtl)
                         for li, line in enumerate(lines)) if t.strip()]
    if not texts:
        return " " if any(t.is_space for t in tokens) else ""
    lead = " " if texts[0][:1].isspace() else ""
    trail = " " if texts[-1][-1:].isspace() else ""
    return lead + " ".join(t.strip() for t in texts) + trail
