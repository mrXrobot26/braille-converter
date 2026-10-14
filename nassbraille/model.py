"""Document model shared by the readers, the review screen and the writers.

A Document is a list of Pages; a Page is an ordered list of Blocks. The same
content can be written as "markup" text, one line per block, which is what the
review screen edits:

    # .. ####  heading level 1..4
    > text     a line inside a boxed note (a blank line ends the box)
    (صورة...)  picture text / picture marker
    anything else is a normal paragraph
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
PICTURE_MARKER = "(صورة)"   # a removed picture whose words could not be read

# Block.flags set by the readers
UNSURE_FLAGS = ("low-font", "unknown-glyph", "suspect-words")   # text may be wrong
PLACED_FLAG = "placed-box"   # a side box moved after the paragraph beside it
KINDS = ("h1", "h2", "h3", "h4", "para", "box", "caption", "picture", "notice")


@dataclass
class Block:
    kind: str                                   # one of KINDS
    text: str
    bboxes: list = field(default_factory=list)  # [(x0, y0, x1, y1)] in page points
    confidence: float = 1.0                     # 0..1, drives review highlighting
    flags: list = field(default_factory=list)   # e.g. "low-font", "unknown-glyph", "placed-box"
    box_id: int | None = None                   # consecutive box blocks sharing an id = one box


@dataclass
class Page:
    number: int                                 # 1-based, as printed order in the source
    blocks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    size: tuple | None = None                   # (width, height) in points, PDF only


@dataclass
class Document:
    source: str
    kind: str                                   # "pdf" | "docx"
    pages: list = field(default_factory=list)
    report: dict = field(default_factory=dict)  # reader statistics for the report screen


def block_to_markup(block):
    if block.kind in HEADINGS:
        return "#" * HEADINGS[block.kind] + " " + block.text
    if block.kind == "box":
        return "> " + block.text
    return block.text


def page_to_markup(page):
    """One line per block; a blank line closes a box."""
    lines, prev_box = [], None
    for block in page.blocks:
        box = block.box_id if block.kind == "box" else None
        if prev_box is not None and box != prev_box:
            lines.append("")
        lines.append(block_to_markup(block))
        prev_box = box
    if prev_box is not None:
        lines.append("")
    return "\n".join(lines)


HEADING_RE = re.compile(r"^(#{1,4}) (.*)$")


def markup_line_to_block(line, box_id=None):
    """Parse one non-blank markup line; box lines get the given box id."""
    m = HEADING_RE.match(line)
    if m:
        return Block(f"h{len(m.group(1))}", m.group(2).strip())
    if line.startswith(">"):
        return Block("box", line[1:].strip(), box_id=box_id)
    stripped = line.strip()
    if stripped == PICTURE_MARKER:
        return Block("picture", stripped)
    if stripped.startswith("(صورة"):
        return Block("caption", stripped)
    return Block("para", stripped)


def markup_to_blocks(text):
    blocks, box_id, in_box = [], 0, False
    for line in text.splitlines():
        if not line.strip():
            if in_box:
                box_id += 1
            in_box = False
            continue
        block = markup_line_to_block(line, box_id)
        in_box = block.kind == "box"
        blocks.append(block)
    return blocks
