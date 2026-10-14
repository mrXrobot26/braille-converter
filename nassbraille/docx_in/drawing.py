"""Find what a run-level drawing holds: text boxes, WordArt, pictures, charts.

Only the mc:Choice branch of mc:AlternateContent is read (ns.children), so a
DrawingML text box and its VML fallback copy are never both returned. Positions
are approximate page coordinates in EMU, used only to order several floating
objects anchored in the same paragraph (top to bottom, then right to left).
"""
from __future__ import annotations

import re

from .ns import NS, URI_CHART, URI_CHARTEX, URI_DIAGRAM, children, q, truthy, w

INLINE = (float("-inf"), 0.0)        # inline objects sit in the text line itself

WP_INLINE = q("wp", "inline")
WP_ANCHOR = q("wp", "anchor")
WP_POSV = q("wp", "positionV")
WP_POSH = q("wp", "positionH")
WP_POSOFFSET = q("wp", "posOffset")
WP_ALIGN = q("wp", "align")
WP_SIMPLEPOS = q("wp", "simplePos")
WP14_PCTV = q("wp14", "pctPosVOffset")
WP14_PCTH = q("wp14", "pctPosHOffset")
A_GRAPHIC = q("a", "graphic")
A_GRAPHICDATA = q("a", "graphicData")
A_XFRM = q("a", "xfrm")
A_OFF = q("a", "off")
A_EXT = q("a", "ext")
A_CHOFF = q("a", "chOff")
A_CHEXT = q("a", "chExt")
A_BLIPFILL = q("a", "blipFill")
PIC_PIC = q("pic", "pic")
WPS_WSP = q("wps", "wsp")
WPS_TXBX = q("wps", "txbx")
WPS_LINKED = q("wps", "linkedTxbx")
WPS_SPPR = q("wps", "spPr")
WPS_BODYPR = q("wps", "bodyPr")
WPG_WGP = q("wpg", "wgp")
WPG_GRPSP = q("wpg", "grpSp")
WPG_GRPSPPR = q("wpg", "grpSpPr")
WPG_FRAME = q("wpg", "graphicFrame")
WPC_WPC = q("wpc", "wpc")
C_CHART = q("c", "chart")
CX_CHART = q("cx", "chart")
DGM_RELIDS = q("dgm", "relIds")
W_TXBXCONTENT = w("txbxContent")
V_SHAPETYPE = q("v", "shapetype")
V_GROUP = q("v", "group")
V_TEXTBOX = q("v", "textbox")
V_TEXTPATH = q("v", "textpath")
V_IMAGEDATA = q("v", "imagedata")
V_IMAGE = q("v", "image")
V_FILL = q("v", "fill")
O_OLEOBJECT = q("o", "OLEObject")
R_ID = q("r", "id")
O_RELID = q("o", "relid")
VML_SHAPES = {q("v", n) for n in ("shape", "rect", "roundrect", "oval", "line", "polyline",
                                  "arc", "curve", "image")}

EMU = {"pt": 12700.0, "in": 914400.0, "cm": 360000.0, "mm": 36000.0, "px": 9525.0,
       "pc": 152400.0, "em": 152400.0, "emu": 1.0, "": 12700.0}
LENGTH = re.compile(r"^\s*(-?[0-9.]+)\s*([a-z]*)\s*$", re.IGNORECASE)
V_ALIGN = {"top": 0.0, "inside": 0.0, "center": 4.5e6, "bottom": 9.0e6, "outside": 9.0e6}
H_ALIGN = {"left": 0.0, "inside": 0.0, "center": 3.0e6, "right": 6.0e6, "outside": 6.0e6}
PAGE_EMU = (10.7e6, 7.6e6)            # A4 height, width: for percentage offsets


class Found:
    """What one w:drawing / w:pict / w:object contains."""

    def __init__(self):
        self.boxes = []        # [((y, x), w:txbxContent, is_wordart)]
        self.wordart = []      # [((y, x), text)]   legacy VML WordArt
        self.pictures = 0
        self.charts = 0
        self.smartart = 0
        self.equations = 0


# -- DrawingML ---------------------------------------------------------------------
def scan_drawing(drawing, found):
    for holder in children(drawing):
        if holder.tag == WP_INLINE:
            pos = INLINE
        elif holder.tag == WP_ANCHOR:
            pos = anchor_pos(holder)
        else:
            continue
        graphic = holder.find(A_GRAPHIC)
        data = graphic.find(A_GRAPHICDATA) if graphic is not None else None
        if data is None:
            found.pictures += 1
            continue
        _graphic_data(data, _Frame(pos), found)


def anchor_pos(anchor):
    if truthy(anchor.get("simplePos")) and anchor.get("simplePos") is not None:
        sp = anchor.find(WP_SIMPLEPOS)
        if sp is not None:
            return (_float(sp.get("y")), _float(sp.get("x")))
    return (_axis(anchor.find(WP_POSV), V_ALIGN, WP14_PCTV, PAGE_EMU[0]),
            _axis(anchor.find(WP_POSH), H_ALIGN, WP14_PCTH, PAGE_EMU[1]))


def _axis(el, aligns, pct_tag, size):
    if el is None:
        return 0.0
    for off in el.iter(WP_POSOFFSET):          # also inside mc:Fallback
        if off.text and off.text.strip():
            return _float(off.text)
    for al in el.iter(WP_ALIGN):
        return aligns.get((al.text or "").strip(), 0.0)
    for pct in el.iter(pct_tag):
        return _float(pct.text) / 100000.0 * size
    return 0.0


class _Frame:
    """Maps child coordinates of a group to page EMU (approximately)."""

    def __init__(self, base, off=(0.0, 0.0), choff=(0.0, 0.0), scale=(1.0, 1.0), parent=None):
        self.base, self.off, self.choff, self.scale, self.parent = base, off, choff, scale, parent

    def map(self, y, x):
        y = self.off[0] + (y - self.choff[0]) * self.scale[0]
        x = self.off[1] + (x - self.choff[1]) * self.scale[1]
        if self.parent is not None:
            return self.parent.map(y, x)
        if self.base == INLINE:
            return (INLINE[0], x)
        return (self.base[0] + y, self.base[1] + x)

    def origin(self):
        if self.base == INLINE and self.parent is None:
            return INLINE
        return self.map(self.choff[0], self.choff[1])


def _xfrm_off(sppr):
    xfrm = sppr.find(A_XFRM) if sppr is not None else None
    off = xfrm.find(A_OFF) if xfrm is not None else None
    if off is None:
        return None
    return (_float(off.get("y")), _float(off.get("x")))


def _graphic_data(data, frame, found):
    uri = data.get("uri", "")
    kids = list(children(data))
    tags = {k.tag for k in kids}
    if uri in (URI_CHART, URI_CHARTEX) or tags & {C_CHART, CX_CHART}:
        found.charts += 1
        return
    if uri == URI_DIAGRAM or DGM_RELIDS in tags:
        found.smartart += 1
        return
    handled = False
    for k in kids:
        if k.tag == PIC_PIC:
            found.pictures += 1
            handled = True
        elif k.tag == WPS_WSP:
            _shape(k, frame.origin(), found)
            handled = True
        elif k.tag in (WPG_WGP, WPC_WPC):
            _group(k, frame, found, top=True)
            handled = True
    if not handled:
        found.pictures += 1                    # ink, 3D models, unknown graphics


def _shape(wsp, pos, found):
    txbx = wsp.find(WPS_TXBX)
    content = txbx.find(W_TXBXCONTENT) if txbx is not None else None
    if content is not None:
        body = wsp.find(WPS_BODYPR)
        art = body is not None and body.get("fromWordArt") is not None and truthy(body.get("fromWordArt"))
        found.boxes.append((pos, content, art))
        return
    if wsp.find(WPS_LINKED) is not None:       # continuation of a linked box: no own text
        return
    sppr = wsp.find(WPS_SPPR)
    if sppr is not None and sppr.find(A_BLIPFILL) is not None:
        found.pictures += 1


def _group(grp, frame, found, top=False):
    props = grp.find(WPG_GRPSPPR)
    xfrm = props.find(A_XFRM) if props is not None else None
    if xfrm is not None:
        off = _pair(xfrm.find(A_OFF))
        ext = _pair(xfrm.find(A_EXT), "cy", "cx")
        choff = _pair(xfrm.find(A_CHOFF))
        chext = _pair(xfrm.find(A_CHEXT), "cy", "cx")
        scale = (ext[0] / chext[0] if chext[0] else 1.0, ext[1] / chext[1] if chext[1] else 1.0)
        inner = _Frame(frame.base, off if not top else (0.0, 0.0), choff, scale,
                       None if top else frame)
    else:
        inner = _Frame(frame.base, parent=None if top else frame)
    for k in children(grp):
        if k.tag == WPS_WSP:
            off = _xfrm_off(k.find(WPS_SPPR))
            pos = inner.map(*off) if off is not None else inner.origin()
            _shape(k, pos, found)
        elif k.tag == PIC_PIC:
            found.pictures += 1
        elif k.tag in (WPG_GRPSP, WPG_WGP):
            _group(k, inner, found)
        elif k.tag == WPG_FRAME:
            graphic = k.find(A_GRAPHIC)
            data = graphic.find(A_GRAPHICDATA) if graphic is not None else None
            if data is not None:
                _graphic_data(data, inner, found)


def _pair(el, ya="y", xa="x"):
    if el is None:
        return (0.0, 0.0)
    return (_float(el.get(ya)), _float(el.get(xa)))


# -- VML -------------------------------------------------------------------------------
def scan_pict(pict, found):
    for k in children(pict):
        _vml(k, None, found)


def _vml(el, frame, found):
    tag = el.tag
    if tag == V_SHAPETYPE:
        return
    if tag == V_GROUP:
        inner = _vml_group_frame(el, frame)
        for k in children(el):
            _vml(k, inner, found)
        return
    if tag not in VML_SHAPES:
        return
    pos = _vml_pos(el, frame)
    box = el.find(V_TEXTBOX)
    content = box.find(W_TXBXCONTENT) if box is not None else None
    if content is not None:
        found.boxes.append((pos, content, False))
        return
    path = el.find(V_TEXTPATH)
    if path is not None and (path.get("string") or "").strip():
        found.wordart.append((pos, path.get("string")))
        return
    if tag == V_IMAGE or el.find(V_IMAGEDATA) is not None:
        found.pictures += 1
        return
    fill = el.find(V_FILL)
    if fill is not None and (fill.get(R_ID) or fill.get(O_RELID)):
        found.pictures += 1


def _style(el):
    out = {}
    for item in (el.get("style") or "").split(";"):
        if ":" in item:
            key, value = item.split(":", 1)
            out[key.strip().lower()] = value.strip()
    return out


def _length(text):
    m = LENGTH.match(text or "")
    if not m:
        return 0.0
    try:
        return float(m.group(1)) * EMU.get(m.group(2).lower(), 12700.0)
    except ValueError:
        return 0.0


def _number(text):
    m = LENGTH.match(text or "")
    try:
        return float(m.group(1)) if m else 0.0
    except ValueError:
        return 0.0


def _vml_pos(el, frame):
    st = _style(el)
    if frame is not None:                         # child of a v:group: coordsize units
        return frame.map(_number(st.get("top", "0")), _number(st.get("left", "0")))
    if st.get("position") != "absolute":
        return INLINE
    top = st.get("margin-top", st.get("top", "0"))
    left = st.get("margin-left", st.get("left", "0"))
    return (_length(top), _length(left))


def _vml_group_frame(group, frame):
    st = _style(group)
    size = _coords(group.get("coordsize"), (1000.0, 1000.0))
    origin = _coords(group.get("coordorigin"), (0.0, 0.0))
    if frame is None:
        base = _vml_pos(group, None)
        height, width = _length(st.get("height", "0")), _length(st.get("width", "0"))
        scale = (height / size[0] if size[0] else 1.0, width / size[1] if size[1] else 1.0)
        return _Frame(base, (0.0, 0.0), origin, scale)
    off = (_number(st.get("top", "0")), _number(st.get("left", "0")))
    height, width = _number(st.get("height", "0")), _number(st.get("width", "0"))
    scale = (height / size[0] if size[0] else 1.0, width / size[1] if size[1] else 1.0)
    return _Frame(frame.base, off, origin, scale, frame)


def _coords(text, default):
    parts = [p for p in (text or "").split(",") if p.strip()]
    if len(parts) != 2:
        return default
    try:
        x, y = float(parts[0]), float(parts[1])
    except ValueError:
        return default
    return (y, x)


# -- OLE objects ---------------------------------------------------------------------------
def scan_object(obj, found):
    found.pictures += 1
    for ole in obj.iter(O_OLEOBJECT):
        if (ole.get("ProgID") or "").lower().startswith("equation"):
            found.equations += 1
            break


def _float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["Found", "INLINE", "scan_drawing", "scan_pict", "scan_object", "anchor_pos", "NS"]
