"""Record what MuPDF draws on a page through a low-level device.

For every glyph we keep its id, ToUnicode text, geometry, font program, the
struct-tree path it belongs to, the ActualText run around it and how much of
it is visible inside the current clip. Images are recorded the same way, so
lines that Word rasterised (with the real text in /ActualText) are not lost.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pymupdf.mupdf as mu

from .fonts import FontRegistry

REPLACEMENT = 0xFFFD


@dataclass
class Glyph:
    gid: int
    tu: str                  # ToUnicode text of the whole cluster (logical order)
    x: float                 # origin
    y: float
    bbox: tuple              # (x0, y0, x1, y1)
    adv: float               # advance width in page units
    size: float
    font: int                # FontRegistry key
    path: tuple              # ((raw, idx, standard), ...) root first
    meta: int | None         # ActualText run id
    vis: float               # 0..1 share of bbox inside the clip
    seq: int                 # draw order on the page
    invisible: bool = False  # render mode 3 (e.g. an OCR layer)


@dataclass
class Picture:
    bbox: tuple
    path: tuple
    meta: int | None
    vis: float
    seq: int
    mask: bool = False


@dataclass
class MetaRun:
    id: int
    text: str
    path: tuple
    seq: int


@dataclass
class PageRecord:
    number: int
    width: float
    height: float
    glyphs: list = field(default_factory=list)
    pictures: list = field(default_factory=list)
    metas: dict = field(default_factory=dict)


def _rect(r):
    return (r.x0, r.y0, r.x1, r.y1)


def _intersect(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def _area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _visible(bbox, clip):
    area = _area(bbox)
    if area <= 0:
        # zero-area glyphs (spaces): judge by their origin point
        x, y = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        return 1.0 if clip[0] <= x <= clip[2] and clip[1] <= y <= clip[3] else 0.0
    return _area(_intersect(bbox, clip)) / area


class Recorder(mu.FzDevice2):
    HOOKS = ("fill_text", "stroke_text", "clip_text", "clip_stroke_text", "ignore_text",
             "fill_image", "fill_image_mask", "clip_image_mask", "clip_path",
             "clip_stroke_path", "pop_clip", "begin_mask", "end_mask", "begin_tile",
             "end_tile", "begin_structure", "end_structure", "begin_metatext",
             "end_metatext")

    def __init__(self, fonts: FontRegistry, record: PageRecord):
        super().__init__()
        for name in self.HOOKS:
            getattr(self, "use_virtual_" + name)()
        self.fonts = fonts
        self.rec = record
        big = 1e6
        self.clips = [(-big, -big, big, big)]
        self.mask_areas = []
        self.hidden = 0            # inside a mask definition or a tile pattern
        self.struct = []           # [(raw, idx, standard)]
        self.metas = []            # [(meta_type, run_id or None)]
        self.active_meta = None
        self.seq = 0
        self.font_cache = {}       # fz_font pointer -> registry key (this page only)

    # ----- helpers
    def _font_key(self, font):
        ptr = font.m_internal_value()
        key = self.font_cache.get(ptr)
        if key is None:
            key = self.fonts.register(font)
            self.font_cache[ptr] = key
        return key

    def _push_clip(self, rect):
        self.clips.append(_intersect(self.clips[-1], rect))

    def _text(self, text, ctm, invisible=False):
        if self.hidden:
            return
        ctm = mu.FzMatrix(ctm)
        path = tuple(self.struct)
        raw = text.head
        while raw:
            span = mu.FzTextSpan(raw)
            font = span.font()
            fkey = self._font_key(font)
            trm = span.trm()
            wmode = raw.wmode
            last = None
            for i in range(raw.len):
                item = span.items(i)
                ucs = item.ucs
                ch = chr(ucs) if 0 < ucs < 0x110000 and ucs != REPLACEMENT else ""
                if item.gid < 0:
                    if last is not None:
                        last.tu += ch       # extra ToUnicode chars of a ligature
                    continue
                m = mu.fz_concat(mu.FzMatrix(trm.a, trm.b, trm.c, trm.d, item.x, item.y), ctm)
                bbox = _rect(mu.fz_bound_glyph(font, item.gid, m))
                adv = mu.fz_advance_glyph(font, item.gid, wmode) * math.hypot(m.a, m.b)
                size = abs(math.hypot(m.c, m.d))
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    bbox = (m.e, m.f - 0.7 * size, m.e + adv, m.f + 0.2 * size)
                self.seq += 1
                last = Glyph(item.gid, ch, m.e, m.f, bbox, adv, size, fkey, path,
                             self.active_meta, _visible(bbox, self.clips[-1]), self.seq,
                             invisible)
                self.rec.glyphs.append(last)
            raw = raw.next

    def _image(self, ctm, mask=False):
        if self.hidden:
            return
        bbox = _rect(mu.fz_transform_rect(mu.FzRect(0, 0, 1, 1), mu.FzMatrix(ctm)))
        self.seq += 1
        self.rec.pictures.append(Picture(bbox, tuple(self.struct), self.active_meta,
                                         _visible(bbox, self.clips[-1]), self.seq, mask))

    # ----- text
    def fill_text(self, ctx, text, ctm, cs, color, alpha, cp):
        self._text(text, ctm)

    def stroke_text(self, ctx, text, stroke, ctm, cs, color, alpha, cp):
        self._text(text, ctm)

    def clip_text(self, ctx, text, ctm, scissor):
        self._text(text, ctm)
        self._push_clip(_rect(mu.fz_bound_text(mu.FzText(mu.ll_fz_keep_text(text)), None,
                                               mu.FzMatrix(ctm))))

    def clip_stroke_text(self, ctx, text, stroke, ctm, scissor):
        self._text(text, ctm)
        self._push_clip(_rect(mu.fz_bound_text(mu.FzText(mu.ll_fz_keep_text(text)), None,
                                               mu.FzMatrix(ctm))))

    def ignore_text(self, ctx, text, ctm):
        self._text(text, ctm, invisible=True)

    # ----- images
    def fill_image(self, ctx, image, ctm, alpha, cp):
        self._image(ctm)

    def fill_image_mask(self, ctx, image, ctm, cs, color, alpha, cp):
        self._image(ctm, mask=True)

    def clip_image_mask(self, ctx, image, ctm, scissor):
        self._push_clip(_rect(mu.fz_transform_rect(mu.FzRect(0, 0, 1, 1), mu.FzMatrix(ctm))))

    # ----- clipping, masks, tiles
    def clip_path(self, ctx, path, even_odd, ctm, scissor):
        self._push_clip(_rect(mu.ll_fz_bound_path(path, None, ctm)))

    def clip_stroke_path(self, ctx, path, stroke, ctm, scissor):
        self._push_clip(_rect(mu.ll_fz_bound_path(path, stroke, ctm)))

    def pop_clip(self, ctx):
        if len(self.clips) > 1:
            self.clips.pop()

    def begin_mask(self, ctx, area, luminosity, cs, color, cp):
        self.hidden += 1
        self.mask_areas.append(_rect(mu.FzRect(area)))

    def end_mask(self, ctx, tr):
        self.hidden = max(0, self.hidden - 1)
        self._push_clip(self.mask_areas.pop() if self.mask_areas else self.clips[-1])

    def begin_tile(self, ctx, area, view, xstep, ystep, ctm, id, doc_id):
        self.hidden += 1
        return 0

    def end_tile(self, ctx):
        self.hidden = max(0, self.hidden - 1)

    # ----- structure and ActualText
    def begin_structure(self, ctx, standard, raw, idx):
        self.struct.append((raw or "", idx, mu.fz_structure_to_string(standard)))

    def end_structure(self, ctx):
        if self.struct:
            self.struct.pop()

    def begin_metatext(self, ctx, meta, text):
        run = None
        if meta == 0 and self.active_meta is None and text is not None:
            run = len(self.rec.metas)
            self.seq += 1
            self.rec.metas[run] = MetaRun(run, text, tuple(self.struct), self.seq)
            self.active_meta = run
        self.metas.append((meta, run))

    def end_metatext(self, ctx):
        if self.metas:
            _, run = self.metas.pop()
            if run is not None and run == self.active_meta:
                self.active_meta = None


def record_page(page, number, fonts):
    rect = page.rect
    record = PageRecord(number, rect.width, rect.height)
    device = Recorder(fonts, record)
    mu.fz_run_page(page.this, device, mu.FzMatrix(), mu.FzCookie())
    return record
