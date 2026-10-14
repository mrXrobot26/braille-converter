"""Assemble a tagged page in struct-tree (reading) order.

Leaves are ActualText runs (logical text written by the PDF producer, used
verbatim) or groups of decoded glyphs. Leaves are grouped into blocks by
their nearest block-level struct element (P, H1.., LI, TD, ...). Word's
"Textbox" elements become boxed notes, tables are linearised, and side boxes
are moved after the paragraph they sit beside.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from itertools import zip_longest

from ..model import PICTURE_MARKER, Block
from .decide import make_tokens
from .lines import tokens_text

BLOCK_TYPES = {"P", "H", "H1", "H2", "H3", "H4", "H5", "H6", "LI", "LBody", "Lbl", "TD",
               "TH", "Caption", "Figure", "Formula", "TOCI", "BlockQuote", "Title", "Note",
               "Aside", "FENote", "Index", "BibEntry", "Code"}
BOX_RAW = {"Textbox", "InlineShape"}
HEADING = {"H1": "h1", "H2": "h2", "H3": "h3", "H4": "h4", "H5": "h4", "H6": "h4",
           "H": "h3", "Title": "h1"}
LIST_ITEM = re.compile(r"^\s*(\(?[0-9٠-٩]+\s?[-.)]|\([ء-ي0-9٠-٩]{1,2}\)|[-–•▪*])")
WESTERN_DIGITS = re.compile(r"[0-9]+")
TO_AI = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
IMAGE_STYLE = "صورة سطر"      # pseudo font of text drawn as pictures
ARABIC_LETTER = re.compile(r"[ء-ي]")


@dataclass
class Atom:
    key: tuple
    path: tuple
    text: str
    bbox: tuple | None
    actual: bool
    size: float
    fonts: collections.Counter = field(default_factory=collections.Counter)
    unknown: int = 0


def _idx(path):
    return tuple(p[1] for p in path)


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def arabic_digits_in_context(text):
    """Western digits stored in the text but drawn as Arabic-Indic (Word's
    'Hindi numerals'): convert runs that follow Arabic text."""
    def repl(m):
        before = text[:m.start()]
        strong = re.findall(r"[A-Za-zء-ي]", before)
        if not strong or ARABIC_LETTER.match(strong[-1]):
            return m.group(0).translate(TO_AI)
        return m.group(0)
    return WESTERN_DIGITS.sub(repl, text)


def _contentless_atoms(atoms, resolver):
    """ActualText of children that draw nothing (inter-word space Spans),
    between the first and last child of each block that has content here."""
    children = collections.defaultdict(set)
    for a in atoms:
        prefix = _block_prefix(a.path)
        if len(a.path) > len(prefix):
            children[prefix].add(a.path[len(prefix)][1])
    extra = []
    for prefix, used in children.items():
        xref = resolver.resolve(prefix)
        if xref is None:
            continue
        kids = resolver.kids(xref)
        for i in range(min(used), max(used) + 1):
            if i in used or i >= len(kids) or kids[i][0] != "ref":
                continue
            if resolver.kids(kids[i][1]):
                continue                     # has content (maybe on another page)
            text = resolver.actual_text(kids[i][1])
            if text:
                extra.append(Atom(_idx(prefix) + (i, 0), prefix + (("Span", i, "Span"),),
                                  text, None, True, 0.0))
    return extra


def page_atoms(rec, fonts, numerals, resolver=None):
    atoms, pictures = [], []
    members = collections.defaultdict(list)
    for g in rec.glyphs:
        if g.meta is not None:
            members[g.meta].append(g)
    for p in rec.pictures:
        if p.meta is not None:
            members[p.meta].append(p)
    for run in rec.metas.values():
        if not run.path:
            continue                       # artifact (header/footer)
        items = members.get(run.id, [])
        bbox = None
        size = 0.0
        if items:
            weights = [max(_area(it.bbox), 1e-6) for it in items]
            vis = sum(w * it.vis for w, it in zip(weights, items)) / sum(weights)
            if vis < 0.5:
                continue                   # clipped away in print
            bbox = _union(it.bbox for it in items)
            size = max((it.bbox[3] - it.bbox[1]) for it in items) * 0.75
        text = run.text
        if numerals == "arabic":
            text = arabic_digits_in_context(text)
        atom = Atom(_idx(run.path) + (run.seq,), run.path, text, bbox, True, size)
        if items and text.strip():
            # a rasterised run: its picture height stands in for a font size
            atom.fonts = collections.Counter({IMAGE_STYLE: len(text.strip())})
        atoms.append(atom)

    leaves = collections.defaultdict(list)
    for g in rec.glyphs:
        if g.meta is None and g.path and g.vis >= 0.5 and not g.invisible:
            leaves[g.path].append(g)
    for path, glyphs in leaves.items():
        tokens = make_tokens(glyphs, fonts)
        text = tokens_text(tokens)
        if not text:
            continue
        sizes = sorted(g.size for g in glyphs)
        atom = Atom(_idx(path) + (min(g.seq for g in glyphs),), path, text,
                    _union(g.bbox for g in glyphs), False, sizes[len(sizes) // 2],
                    collections.Counter(g.font for g in glyphs))
        atom.unknown = sum(1 for t in text if 0xE000 <= ord(t) <= 0xF8FF or t == "�")
        atoms.append(atom)

    if resolver is not None:
        atoms.extend(_contentless_atoms(atoms, resolver))

    figures = {}
    for p in rec.pictures:
        if p.meta is None and p.path and p.vis >= 0.5:
            for i, (raw, _, std) in enumerate(p.path):
                if std == "Figure" or raw == "Figure":
                    fig = p.path[:i + 1]
                    figures.setdefault(fig, []).append(p)
                    break
    for fig, pics in figures.items():
        atoms.append(Atom(_idx(fig) + (min(p.seq for p in pics),), fig, PICTURE_MARKER,
                          _union(p.bbox for p in pics), True, 0.0))
    return atoms


def _block_prefix(path):
    for i in range(len(path) - 1, -1, -1):
        raw, _, std = path[i]
        if std in BLOCK_TYPES or raw in BLOCK_TYPES:
            return path[:i + 1]
    return path


def _same_line(a, b):
    if not a.bbox or not b.bbox:
        return False
    top, bottom = max(a.bbox[1], b.bbox[1]), min(a.bbox[3], b.bbox[3])
    h = min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1])
    return h > 0 and bottom - top >= 0.5 * h


def _join(atoms):
    text, prev = "", None
    for a in atoms:
        t = a.text
        if prev is None or (prev.actual and a.actual):
            text += t
        elif text.endswith((" ", "\n")) or t.startswith((" ", "\n")):
            text += t
        elif _same_line(prev, a):
            gap = max(prev.bbox[0] - a.bbox[2], a.bbox[0] - prev.bbox[2])
            text += t if gap < 0.15 * max(prev.size, a.size, 1.0) else " " + t
        else:
            text += " " + t
        prev = a
    return " ".join(text.split())


@dataclass
class RawBlock:
    prefix: tuple
    atoms: list
    kind: str = "para"
    box: tuple | None = None       # textbox prefix
    table: tuple | None = None     # table prefix
    row: tuple | None = None
    cell: tuple | None = None

    @property
    def bbox(self):
        return _union(a.bbox for a in self.atoms)


def _classify(rb):
    path = rb.atoms[0].path
    for i, (raw, _, std) in enumerate(path):
        if raw in BOX_RAW and rb.box is None:
            rb.box = path[:i + 1]
        if std == "Table" and rb.table is None:
            rb.table = path[:i + 1]
        if std == "TR":
            rb.row = path[:i + 1]
        if std in ("TD", "TH"):
            rb.cell = path[:i + 1]
    last_raw, _, last_std = rb.prefix[-1] if rb.prefix else ("", 0, "")
    if any(a.text == PICTURE_MARKER for a in rb.atoms) and (last_std == "Figure" or
                                                           last_raw == "Figure"):
        rb.kind = "picture"
    elif last_std in HEADING:
        rb.kind = HEADING[last_std]
    elif rb.box is not None:
        rb.kind = "box"


def _linearize(rows):
    rows = [[c for c in r if c.strip()] for r in rows]
    rows = [r for r in rows if r]
    if not rows:
        return []

    def short(c, n):
        return len(c.split()) <= n
    if len(rows) == 2 and all(short(c, 4) for c in rows[0]) and len(rows[1]) > 1:
        return [f"{h}: {v}" if h and v else (h or v)
                for h, v in zip_longest(rows[0], rows[1], fillvalue="")]
    if all(len(r) == 2 for r in rows) and all(short(r[0], 6) for r in rows):
        return [f"{r[0]}: {r[1]}" for r in rows]
    return [c for r in rows for c in r]


def assemble(atoms):
    atoms.sort(key=lambda a: a.key)
    groups = collections.OrderedDict()
    for a in atoms:
        groups.setdefault(_block_prefix(a.path), []).append(a)
    raw_blocks = []
    for prefix, items in groups.items():
        rb = RawBlock(prefix, items)
        _classify(rb)
        raw_blocks.append(rb)

    box_ids = {}
    out = []          # (Block, bbox)
    i = 0
    while i < len(raw_blocks):
        rb = raw_blocks[i]
        if rb.table is not None:
            j = i
            rows = collections.OrderedDict()
            while j < len(raw_blocks) and raw_blocks[j].table == rb.table:
                cell_rb = raw_blocks[j]
                row = rows.setdefault(cell_rb.row, collections.OrderedDict())
                row.setdefault(cell_rb.cell, []).append(_join(cell_rb.atoms))
                j += 1
            lines = _linearize([[" ".join(parts) for parts in row.values()]
                                for row in rows.values()])
            bbox = _union(raw_blocks[k].bbox for k in range(i, j))
            kind = "box" if rb.box is not None else "para"
            box_id = box_ids.setdefault(rb.box, len(box_ids)) if rb.box is not None else None
            for line in lines:
                out.append((Block(kind, line, [bbox] if bbox else [], box_id=box_id), bbox))
            i = j
            continue
        text = _join(rb.atoms)
        if text:
            box_id = box_ids.setdefault(rb.box, len(box_ids)) if rb.kind == "box" else None
            block = Block(rb.kind, text, [rb.bbox] if rb.bbox else [], box_id=box_id)
            unknown = sum(a.unknown for a in rb.atoms)
            if unknown:
                block.flags.append("unknown-glyph")
                block.confidence = 0.5
            block.fonts = sum((a.fonts for a in rb.atoms), collections.Counter())
            block.actual = all(a.actual for a in rb.atoms)
            block.size = max((a.size for a in rb.atoms), default=0.0)
            out.append((block, rb.bbox))
        i += 1
    return place_boxes(out)


def _vertical_overlap(a, b):
    return min(a[3], b[3]) - max(a[1], b[1])


def place_boxes(items):
    """Move each side box after the main paragraph it sits beside."""
    main = [(b, bb) for b, bb in items if b.kind != "box"]
    groups = collections.OrderedDict()
    order_before = {}
    seen_main = -1
    for b, bb in items:
        if b.kind == "box":
            groups.setdefault(b.box_id, []).append((b, bb))
            order_before.setdefault(b.box_id, seen_main)
        else:
            seen_main += 1
    after = collections.defaultdict(list)
    for box_id, members in groups.items():
        bbox = _union(bb for _, bb in members)
        anchor = order_before[box_id]
        if bbox:
            overlapping = []
            for k, (b, bb) in enumerate(main):
                if not bb:
                    continue
                ov = _vertical_overlap(bb, bbox)
                small = min(bb[3] - bb[1], bbox[3] - bbox[1])
                if ov >= 0.25 * small or ov >= 6:
                    overlapping.append(k)
            if overlapping:
                anchor = overlapping[-1]
                text = main[anchor][0].text.rstrip()
                if text.endswith(":") or LIST_ITEM.match(main[anchor][0].text):
                    while anchor + 1 < len(main) and LIST_ITEM.match(main[anchor + 1][0].text):
                        anchor += 1
                for b, _ in members:
                    if "placed-box" not in b.flags:
                        b.flags.append("placed-box")
        after[anchor].append((bbox, members))
    result = []
    for anchor_k in [-1]:
        for _, members in sorted(after.get(anchor_k, []), key=lambda m: _box_key(m[0])):
            result.extend(b for b, _ in members)
    for k, (b, _) in enumerate(main):
        result.append(b)
        for _, members in sorted(after.get(k, []), key=lambda m: _box_key(m[0])):
            result.extend(b2 for b2, _ in members)
    return result


def _box_key(bbox):
    return (bbox[1], -bbox[2]) if bbox else (0, 0)
