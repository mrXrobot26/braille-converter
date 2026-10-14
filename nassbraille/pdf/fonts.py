"""Font registry and the font-program decoder.

Fonts are keyed by a hash of their program bytes, not by name: Word embeds
two different subsets under the same name. For each program we can derive
gid -> text from the font itself (legacy private-code tables, the reversed
Unicode cmap, glyph names, and a GSUB closure for ligatures/forms). Whether
that or the PDF's ToUnicode is trusted is decided per font in decide.py.
"""
from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field

from fontTools import agl
from fontTools.ttLib import TTFont

from .legacy import TABLES

SUBSET_TAG = re.compile(r"^[A-Z]{6}\+")


def _is_pua(text):
    return any(0xE000 <= ord(c) <= 0xF8FF for c in text)


def _code_rank(code):
    """Lower is preferred when one glyph has several code points."""
    if 0x0621 <= code <= 0x064A or 0x0660 <= code <= 0x0669 or code < 0x0250:
        return (0, code)
    if 0x0600 <= code <= 0x06FF:
        return (1, code)
    if 0xFB50 <= code <= 0xFEFF:
        return (3, code)
    return (2, code)


def name_to_text(name):
    """Text of a glyph name (uniXXXX, uXXXXX, AGL names, '_' ligatures)."""
    base = name.split(".")[0]
    if not base or base in (".notdef", "notdef"):
        return None
    parts = base.split("_")
    out = []
    for part in parts:
        m = re.fullmatch(r"uni((?:[0-9A-Fa-f]{4})+)", part)
        if m:
            h = m.group(1)
            out.append("".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4)))
            continue
        m = re.fullmatch(r"u([0-9A-Fa-f]{4,6})", part)
        if m:
            out.append(chr(int(m.group(1), 16)))
            continue
        t = agl.toUnicode(part)
        if not t:
            return None
        out.append(t)
    text = "".join(out)
    return None if not text or _is_pua(text) else text


@dataclass
class FontInfo:
    key: int
    name: str
    data: bytes | None
    bold: bool
    substitute: bool
    analysed: bool = False
    legacy: bool = False
    gid_text: dict = field(default_factory=dict)   # from the font program
    space_gids: set = field(default_factory=set)
    mark_gids: set = field(default_factory=set)
    space_em: float = 0.25                          # space advance / em
    choice: str = "tounicode"                       # tounicode | font
    scores: dict = field(default_factory=dict)

    def analyse(self):
        if self.analysed:
            return self
        self.analysed = True
        if not self.data or self.substitute:
            return self
        try:
            font = TTFont(io.BytesIO(self.data), lazy=True)
            order = font.getGlyphOrder()
        except Exception:
            return self
        self._analyse(font, order)
        return self

    def _analyse(self, font, order):
        index = {name: gid for gid, name in enumerate(order)}
        text = {}
        cmaps = []
        try:
            cmaps = font["cmap"].tables
        except Exception:
            pass

        # legacy private-code fonts: (3,0) symbol cmap mostly in one 0xFx00 block
        for st in cmaps:
            if st.platformID == 3 and st.platEncID == 0 and st.cmap:
                codes = list(st.cmap)
                blocks = {}
                for c in codes:
                    blocks[c >> 8] = blocks.get(c >> 8, 0) + 1
                hi, n = max(blocks.items(), key=lambda kv: kv[1])
                if hi in TABLES and n >= 0.8 * len(codes):
                    self.legacy = True
                    table = TABLES[hi]
                    for code, gname in st.cmap.items():
                        if code >> 8 == hi and (code & 0xFF) in table and gname in index:
                            text.setdefault(gname, table[code & 0xFF])

        # Unicode cmaps reversed (skip private-use). A glyph shared by several
        # code points (Arial: ي and Persian ی) gets the basic Arabic letter.
        best = {}
        for st in cmaps:
            if (st.platformID, st.platEncID) in ((3, 1), (3, 10)) or st.platformID == 0:
                for code, gname in st.cmap.items():
                    if 0xE000 <= code <= 0xF8FF or gname in text:
                        continue
                    if gname not in best or _code_rank(code) < _code_rank(best[gname]):
                        best[gname] = code
        for gname, code in best.items():
            text[gname] = chr(code)

        # glyph names
        for gname in order:
            if gname not in text:
                t = name_to_text(gname)
                if t:
                    text[gname] = t

        # GSUB closure: forms and ligatures inherit their source text
        try:
            gsub = font["GSUB"].table if "GSUB" in font else None
        except Exception:
            gsub = None
        if gsub is not None and gsub.LookupList:
            def subtables():
                for lookup in gsub.LookupList.Lookup:
                    for st in lookup.SubTable:
                        if lookup.LookupType == 7:
                            st = st.ExtSubTable
                        yield st
            for _ in range(12):
                changed = False
                for st in subtables():
                    kind = type(st).__name__
                    if kind == "SingleSubst":
                        for a, b in st.mapping.items():
                            if b not in text and a in text:
                                text[b] = text[a]
                                changed = True
                    elif kind == "AlternateSubst":
                        for a, alts in st.alternates.items():
                            for b in alts:
                                if b not in text and a in text:
                                    text[b] = text[a]
                                    changed = True
                    elif kind == "LigatureSubst":
                        for first, ligs in st.ligatures.items():
                            for lig in ligs:
                                comps = [first] + list(lig.Component)
                                if lig.LigGlyph not in text and all(c in text for c in comps):
                                    text[lig.LigGlyph] = "".join(text[c] for c in comps)
                                    changed = True
                    elif kind == "MultipleSubst":
                        for a, seq in st.mapping.items():
                            if seq and seq[0] not in text and a in text:
                                text[seq[0]] = text[a]
                                for extra in seq[1:]:
                                    text.setdefault(extra, "")   # zero-width residue
                                changed = True
                if not changed:
                    break

        # GDEF mark class and empty outlines (spaces)
        marks = set()
        try:
            gdef = font["GDEF"].table if "GDEF" in font else None
            if gdef is not None and gdef.GlyphClassDef:
                marks = {g for g, c in gdef.GlyphClassDef.classDefs.items() if c == 3}
        except Exception:
            pass
        try:
            hmtx = font["hmtx"].metrics
            upem = font["head"].unitsPerEm or 1000
        except Exception:
            hmtx, upem = {}, 1000
        empty = set()
        try:
            if "glyf" in font:
                glyf = font["glyf"]
                for gname in order:
                    g = glyf[gname]
                    if getattr(g, "numberOfContours", 0) == 0:
                        empty.add(gname)
        except Exception:
            pass

        for gname, t in text.items():
            gid = index.get(gname)
            if gid is not None:
                self.gid_text[gid] = unicodedata.normalize("NFKC", t) if t.strip() else (
                    " " if t else "")
        for gname in empty:
            adv = hmtx.get(gname, (0, 0))[0]
            gid = index[gname]
            if adv > 0 and self.gid_text.get(gid, " ") in (" ", " "):
                self.space_gids.add(gid)
                self.gid_text[gid] = " "
        # the real space advance: U+0020, or the legacy private code 0xFx20
        space_name = None
        for st in cmaps:
            for code in (0x20, 0xF020, 0xF120, 0xF220, 0xF320):
                if st.cmap and code in st.cmap and st.cmap[code] in hmtx:
                    space_name = st.cmap[code]
                    break
            if space_name:
                break
        if not space_name and self.space_gids:
            space_name = order[min(self.space_gids)]
        if space_name and hmtx.get(space_name, (0, 0))[0] > 0:
            self.space_em = hmtx[space_name][0] / upem
        for gname in marks:
            if gname in index:
                self.mark_gids.add(index[gname])


class FontRegistry:
    def __init__(self):
        self.fonts = []
        self.by_hash = {}

    def register(self, font):
        name = SUBSET_TAG.sub("", font.fz_font_name())
        data = None
        buf = font.m_internal.buffer
        if buf:
            import pymupdf.mupdf as mu
            data = mu.FzBuffer(mu.ll_fz_keep_buffer(buf)).fz_buffer_extract_copy()
        substitute = False
        try:
            substitute = bool(font.m_internal.flags.ft_substitute)
        except Exception:
            pass
        digest = hashlib.sha1(data).hexdigest() if data else "name:" + name
        digest += ":sub" if substitute else ""
        key = self.by_hash.get(digest)
        if key is None:
            key = len(self.fonts)
            self.by_hash[digest] = key
            bold = bool(font.fz_font_is_bold()) or "bold" in name.lower()
            self.fonts.append(FontInfo(key, name, data, bold, substitute))
        return key

    def __getitem__(self, key):
        return self.fonts[key]
