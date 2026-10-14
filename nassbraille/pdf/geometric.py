"""Reading order from geometry alone (untagged PDFs, or pages whose tags
don't cover the text).

1. Visible glyphs (plus positioned ActualText runs) -> line fragments: same
   baseline, split at wide gaps (side-by-side items, column gutters).
2. Fragments inside a drawn rectangle belong to that box.
3. Fragments are chained into streams: a line continues the stream above it
   when it starts at (about) the same edge - the right edge for Arabic - and
   overlaps it horizontally. Streams are read top to bottom; two streams that
   start on the same line are read right to left. That gives columns, side
   items and centred headings their natural order.
4. Inside a stream, lines merge into paragraphs unless the previous line was
   short, the next one starts a list item, the size changes or there is a gap.
5. Boxes are placed after the paragraph they sit beside.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..model import Block
from .decide import make_tokens
from .lines import Token, is_rtl_text, split_lines, tokens_text
from .tagged import LIST_ITEM, place_boxes

DIGITS = re.compile(r"[0-9٠-٩]+")


@dataclass
class Frag:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    base: float          # baseline
    size: float
    fonts: dict = field(default_factory=dict)
    box: int | None = None

    @property
    def width(self):
        return self.x1 - self.x0


def _meta_tokens(rec):
    """ActualText runs (BDC form) as atomic tokens with their own text."""
    members = {}
    for g in rec.glyphs:
        if g.meta is not None:
            members.setdefault(g.meta, []).append(g.bbox)
    for p in rec.pictures:
        if p.meta is not None:
            members.setdefault(p.meta, []).append(p.bbox)
    out = []
    for run in rec.metas.values():
        boxes = members.get(run.id)
        if not boxes or not run.text.strip():
            continue
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        size = max(4.0, (y1 - y0) * 0.75)
        out.append(Token(run.text.strip(), x0, x1, y1 - 0.22 * (y1 - y0), size, 0.25,
                         False, False, False, run.seq, (x0 + x1) / 2))
    return out


def _fragments(rec, fonts):
    glyphs = [g for g in rec.glyphs if g.vis >= 0.5 and not g.invisible and g.meta is None]
    if not glyphs and not rec.metas:
        glyphs = [g for g in rec.glyphs if g.invisible]    # an OCR text layer
    tokens = make_tokens(glyphs, fonts) + _meta_tokens(rec)
    if not tokens:
        return [], True
    rtl = is_rtl_text(tokens)
    font_of = {g.seq: g.font for g in glyphs}
    lines, attached = split_lines(tokens)
    frags = []
    for li, line in enumerate(lines):
        line = sorted(line, key=lambda t: -t.cx if rtl else t.cx)
        groups, cur, prev = [], [], None
        for t in line:
            if prev is not None and not t.is_space:
                gap = (prev.x0 - t.x1) if rtl else (t.x0 - prev.x1)
                if gap > 2.0 * max(prev.size, t.size):
                    groups.append(cur)
                    cur = []
            cur.append(t)
            if not t.is_space:
                prev = t
        if cur:
            groups.append(cur)
        for group in groups:
            ids = {id(t) for t in group}
            marks = [m for (lj, bid), ms in attached.items() if lj == li and bid in ids
                     for m in ms]
            text = tokens_text(group + marks, rtl).strip()
            solid = [t for t in group if not t.is_space]
            if not text or not solid:
                continue
            size = max(t.size for t in solid)
            base = sorted(t.y for t in solid)[len(solid) // 2]
            fdict = {}
            for t in solid:
                f = font_of.get(t.seq)
                if f is not None:
                    fdict[f] = fdict.get(f, 0) + 1
            frags.append(Frag(text, min(t.x0 for t in solid), base - 0.8 * size,
                              max(t.x1 for t in solid), base + 0.25 * size, base, size,
                              fdict))
    return frags, rtl


def _assign_boxes(frags, rects):
    """Smallest drawn rectangle holding the fragment's centre and most of it."""
    for f in frags:
        best = None
        cx, cy = (f.x0 + f.x1) / 2, (f.y0 + f.y1) / 2
        for i, r in enumerate(rects):
            if not (r[0] <= cx <= r[2] and r[1] <= cy <= r[3]):
                continue
            inside = max(0.0, min(f.x1, r[2]) - max(f.x0, r[0]))
            if f.width > 0 and inside < 0.8 * f.width:
                continue
            area = (r[2] - r[0]) * (r[3] - r[1])
            if best is None or area < best[0]:
                best = (area, i)
        f.box = best[1] if best else None


def _streams(frags, rtl):
    frags = sorted(frags, key=lambda f: (f.base, -f.x1 if rtl else f.x0))
    streams = []
    for f in frags:
        best = None
        for s in streams:
            last = s[-1]
            if f.base <= last.base + 0.3 * f.size:
                continue                                  # same line or above
            if f.base - last.base > 2.0 * max(f.size, last.size):
                continue
            edge = abs(f.x1 - last.x1) if rtl else abs(f.x0 - last.x0)
            overlap = min(f.x1, last.x1) - max(f.x0, last.x0)
            if edge <= 2.5 * f.size and overlap >= 0.5 * min(f.width, last.width):
                d = f.base - last.base
                if best is None or d < best[0]:
                    best = (d, s)
        if best:
            best[1].append(f)
        else:
            streams.append([f])
    streams.sort(key=lambda s: (round(s[0].base / max(s[0].size, 1)),
                                -s[0].x1 if rtl else s[0].x0))
    return streams


def _paragraphs(stream, rtl):
    left = min(f.x0 for f in stream)
    right = max(f.x1 for f in stream)
    width = max(right - left, 1.0)
    paras, cur = [], [stream[0]]
    for prev, f in zip(stream, stream[1:]):
        short = ((prev.x0 - left) if rtl else (right - prev.x1)) > 0.15 * width
        gap = f.base - prev.base > 1.6 * max(f.size, prev.size)
        if short or gap or abs(f.size - prev.size) > 1.0 or LIST_ITEM.match(f.text):
            paras.append(cur)
            cur = [f]
        else:
            cur.append(f)
    paras.append(cur)
    return paras


def page_rects(page, rec):
    """Box candidates from the drawings: rectangles at least 40 x 12 pt that
    don't cover most of the page."""
    out = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return out
    page_area = rec.width * rec.height
    for d in drawings:
        fill, stroke = d.get("fill"), d.get("color")
        if stroke is None and (fill is None or all(c > 0.97 for c in fill)):
            continue
        for item in d.get("items", []):
            if item[0] == "re":
                r = item[1]
                rect = (r.x0, r.y0, r.x1, r.y1)
            elif item[0] == "qu":
                q = item[1].rect
                rect = (q.x0, q.y0, q.x1, q.y1)
            else:
                continue
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            if w >= 40 and h >= 12 and w * h < 0.85 * page_area:
                out.append(rect)
    return out


def geometric_blocks(rec, fonts, rects=(), drop=None):
    """drop(frag) -> True removes headers/footers found document-wide."""
    frags, rtl = _fragments(rec, fonts)
    if drop is not None:
        frags = [f for f in frags if not drop(rec, f)]
    if not frags:
        return []
    _assign_boxes(frags, list(rects))
    items = []
    regions = {}
    for f in frags:
        regions.setdefault(f.box, []).append(f)
    box_ids = {}
    ordered = []
    for box, members in regions.items():
        for stream in _streams(members, rtl):
            for para in _paragraphs(stream, rtl):
                ordered.append((box, para))
    # main flow in stream order; each box goes in front of the first main
    # paragraph that starts below its top (place_boxes then moves side boxes)
    main = [(b, p) for b, p in ordered if b is None]
    boxes = {}
    for b, p in ordered:
        if b is not None:
            boxes.setdefault(b, []).append((b, p))
    sequence = list(main)
    for b, members in sorted(boxes.items(), key=lambda kv: min(f.y0 for _, p in kv[1]
                                                                 for f in p)):
        top = min(f.y0 for _, p in members for f in p)
        at = next((i for i, (bb, p) in enumerate(sequence)
                   if bb is None and min(f.y0 for f in p) > top), len(sequence))
        sequence[at:at] = members
    for box, para in sequence:
        text = " ".join(f.text for f in para)
        bbox = (min(f.x0 for f in para), min(f.y0 for f in para),
                max(f.x1 for f in para), max(f.y1 for f in para))
        if box is None:
            block = Block("para", text, [bbox])
        else:
            block = Block("box", text, [bbox], box_id=box_ids.setdefault(box, len(box_ids)))
        block.size = max(f.size for f in para)
        block.fonts = {}
        for f in para:
            for k, v in f.fonts.items():
                block.fonts[k] = block.fonts.get(k, 0) + v
        block.lines = len(para)
        items.append((block, bbox))
    # main blocks sorted by position of their stream order already; boxes after
    # the paragraph they sit beside
    return place_boxes(items)


def repeated_bands(records, fonts):
    """Header/footer detector: fragments in the top 8% / bottom 10% whose text
    (digits masked) repeats on >= 40% of pages, and lone page numbers."""
    counts = {}
    per_page = []
    for rec in records:
        seen = set()
        frags, _ = _fragments(rec, fonts)
        for f in frags:
            if f.y1 < 0.08 * rec.height or f.y0 > 0.90 * rec.height:
                key = DIGITS.sub("#", " ".join(f.text.split()))
                seen.add(key)
        per_page.append(seen)
        for key in seen:
            counts[key] = counts.get(key, 0) + 1
    n = max(len(records), 1)
    repeated = {k for k, c in counts.items() if c >= 3 and c >= 0.4 * n}

    def drop(rec, f):
        if not (f.y1 < 0.08 * rec.height or f.y0 > 0.90 * rec.height):
            return False
        key = DIGITS.sub("#", " ".join(f.text.split()))
        return key in repeated or re.fullmatch(r"[-–\s#]*#[-–\s#]*", key) is not None
    return drop
