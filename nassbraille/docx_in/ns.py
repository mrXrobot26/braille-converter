"""XML namespaces and small lxml helpers shared by the DOCX reader."""
from __future__ import annotations

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "wpc": "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "cx": "http://schemas.microsoft.com/office/drawing/2014/chartex",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
}

URI_PICTURE = "http://schemas.openxmlformats.org/drawingml/2006/picture"
URI_CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
URI_CHARTEX = "http://schemas.microsoft.com/office/drawing/2014/chartex"
URI_DIAGRAM = "http://schemas.openxmlformats.org/drawingml/2006/diagram"


def q(prefix, name):
    """Clark notation tag, e.g. q("w", "p") -> "{...main}p"."""
    return "{%s}%s" % (NS[prefix], name)


W = "{%s}" % NS["w"]
W_VAL = W + "val"
MC_ALT = q("mc", "AlternateContent")
MC_CHOICE = q("mc", "Choice")
MC_FALLBACK = q("mc", "Fallback")


def w(name):
    return W + name


def attr(el, name, default=None):
    """A w:-namespaced attribute of `el` (None-safe)."""
    if el is None:
        return default
    return el.get(W + name, default)


def val(el, default=None):
    return attr(el, "val", default)


def int_val(el, default=None):
    v = val(el)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            return default


def truthy(text):
    return text is None or text.strip().lower() not in ("0", "false", "off", "none")


def on_off(el):
    """Value of an ST_OnOff property element: None when the element is missing,
    True when present without w:val or with a true value."""
    if el is None:
        return None
    return truthy(el.get(W_VAL))


def children(el):
    """Child elements of `el`; mc:AlternateContent is replaced by the children of
    its first mc:Choice (mc:Fallback only when there is no Choice at all)."""
    if el is None:
        return
    for ch in el:
        tag = ch.tag
        if not isinstance(tag, str):          # comments, processing instructions
            continue
        if tag == MC_ALT:
            branch = ch.find(MC_CHOICE)
            if branch is None:
                branch = ch.find(MC_FALLBACK)
            if branch is not None:
                yield from children(branch)
            continue
        yield ch


def find(el, tag):
    """First child with `tag`, looking through mc:AlternateContent (Choice)."""
    if el is None:
        return None
    for ch in children(el):
        if ch.tag == tag:
            return ch
    return None


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""
