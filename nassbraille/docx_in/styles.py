"""Style lookups: basedOn chains, outline (heading) levels, inherited properties."""
from __future__ import annotations

import re

from .ns import W, attr, on_off, val

# Built-in heading styles are stored under their English names ("heading 1",
# "Title") whatever the UI language; Arabic Word only changes the style *id*
# (often "1", "2" ...). Other producers sometimes store the Arabic UI name.
HEADING_NAME = re.compile(r"^\s*(?:heading|عنوان)\s*([1-9])\s*$", re.IGNORECASE)
HEADING_ID = re.compile(r"^Heading([1-9])$", re.IGNORECASE)
TITLE_NAMES = {"title", "العنوان"}

W_STYLE = W + "style"
W_PPR = W + "pPr"
W_RPR = W + "rPr"
W_PSTYLE = W + "pStyle"
W_BASEDON = W + "basedOn"
W_NAME = W + "name"
W_OUTLINE = W + "outlineLvl"


class StyleSheet:
    def __init__(self, styles_root=None):
        self.by_id = {}
        self.default = {}
        self.doc_ppr = None
        self.doc_rpr = None
        self._chains = {}
        if styles_root is None:
            return
        for st in styles_root.findall(W_STYLE):
            sid = attr(st, "styleId")
            if sid is None:
                continue
            self.by_id.setdefault(sid, st)
            if on_off_attr(attr(st, "default")):
                self.default.setdefault(attr(st, "type", "paragraph"), sid)
        defaults = styles_root.find(W + "docDefaults")
        if defaults is not None:
            ppr_default = defaults.find(W + "pPrDefault")
            rpr_default = defaults.find(W + "rPrDefault")
            if ppr_default is not None:
                self.doc_ppr = ppr_default.find(W_PPR)
            if rpr_default is not None:
                self.doc_rpr = rpr_default.find(W_RPR)

    # -- chains ---------------------------------------------------------------
    def chain(self, style_id):
        """Style elements from `style_id` up its basedOn chain (nearest first)."""
        if style_id is None:
            return ()
        cached = self._chains.get(style_id)
        if cached is not None:
            return cached
        out, seen, sid = [], set(), style_id
        while sid is not None and sid not in seen and len(out) < 32:
            seen.add(sid)
            st = self.by_id.get(sid)
            if st is None:
                break
            out.append(st)
            sid = val(st.find(W_BASEDON))
        result = tuple(out)
        self._chains[style_id] = result
        return result

    def para_style_id(self, p):
        ppr = p.find(W_PPR)
        sid = val(ppr.find(W_PSTYLE)) if ppr is not None else None
        if sid is not None and sid in self.by_id:
            return sid
        return self.default.get("paragraph")

    def ppr_child(self, style_id, tag):
        """`tag` element from the nearest style pPr in the chain, then docDefaults."""
        for st in self.chain(style_id):
            ppr = st.find(W_PPR)
            if ppr is not None:
                el = ppr.find(tag)
                if el is not None:
                    return el
        if self.doc_ppr is not None:
            return self.doc_ppr.find(tag)
        return None

    def rpr_child(self, style_id, tag, defaults=True):
        for st in self.chain(style_id):
            rpr = st.find(W_RPR)
            if rpr is not None:
                el = rpr.find(tag)
                if el is not None:
                    return el
        if defaults and self.doc_rpr is not None:
            return self.doc_rpr.find(tag)
        return None

    # -- headings -------------------------------------------------------------
    def outline_level(self, ppr, style_id):
        """0-based outline level of a paragraph, or None for body text.

        Direct w:outlineLvl wins, then the style chain (nearest style first), where
        a style counts as a heading through its own w:outlineLvl or because it is
        the built-in "heading N" / "Title" style. As in Word, the level of a
        built-in "heading N" style cannot be changed by direct formatting.
        """
        own = self.by_id.get(style_id) if style_id is not None else None
        if own is not None:
            m = HEADING_NAME.match(style_name(own))
            if m and not style_name(own).startswith("عنوان"):
                return int(m.group(1)) - 1
        if ppr is not None:
            el = ppr.find(W_OUTLINE)
            if el is not None:
                return _outline(el)
        for st in self.chain(style_id):
            sppr = st.find(W_PPR)
            if sppr is not None:
                el = sppr.find(W_OUTLINE)
                if el is not None:
                    return _outline(el)
            level = builtin_heading_level(st)
            if level is not None:
                return level
        return None


def on_off_attr(text):
    return text is not None and text.strip().lower() in ("1", "true", "on")


def style_name(st):
    return (val(st.find(W_NAME)) or "").strip()


def builtin_heading_level(st):
    name = style_name(st)
    m = HEADING_NAME.match(name)
    if m:
        return int(m.group(1)) - 1
    if name.lower() in TITLE_NAMES:
        return 0
    sid = attr(st, "styleId") or ""
    m = HEADING_ID.match(sid)
    if m:
        return int(m.group(1)) - 1
    if sid.lower() == "title":
        return 0
    return None


def _outline(el):
    try:
        level = int(val(el, "9"))
    except ValueError:
        return None
    return level if 0 <= level <= 8 else None


def heading_kind(level):
    """Outline level 0..8 -> "h1".."h4" (deeper levels are h4)."""
    if level is None:
        return None
    return "h%d" % (min(level, 3) + 1)


def is_on(el):
    return bool(on_off(el))
