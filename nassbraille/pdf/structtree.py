"""Tagged-PDF helpers.

MuPDF reports a struct level to devices only when its /S type is standard or
role-mapped. Word writes non-standard types such as "Textbox" without a
RoleMap, so those levels vanish and two text boxes on a page collide. We map
every unknown type to /Div in memory (the file on disk is never touched); the
raw name still reaches the device, so "Textbox" stays recognisable.
"""
from __future__ import annotations

import re

STANDARD = {
    "Document", "DocumentFragment", "Part", "Art", "Sect", "Div", "Aside", "NonStruct",
    "Private", "P", "H", "H1", "H2", "H3", "H4", "H5", "H6", "Title", "FENote", "Sub", "Lbl",
    "Em", "Strong", "L", "LI", "LBody", "Table", "TR", "TH", "TD", "THead", "TBody", "TFoot",
    "Caption", "Figure", "Formula", "Form", "Span", "Quote", "Note", "Reference", "BibEntry",
    "Code", "Link", "Annot", "Ruby", "RB", "RT", "RP", "Warichu", "WT", "WP", "BlockQuote",
    "TOC", "TOCI", "Index", "Artifact",
}


def struct_root(doc):
    kind, val = doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")
    if kind != "xref":
        return None
    return int(val.split()[0])


def is_marked(doc):
    return doc.xref_get_key(doc.pdf_catalog(), "MarkInfo/Marked")[1] == "true"


_K_TOKEN = re.compile(r"<<(.*?)>>|(\d+) (\d+) R|(-?\d+)", re.S)


class StructResolver:
    """Find struct elements by the (raw, idx) path MuPDF reports, and read
    their children. Used to recover content-less children that carry only an
    /ActualText (Word writes every inter-word space of rasterised runs as an
    empty Span with ActualText " ")."""

    def __init__(self, doc):
        self.doc = doc
        self.root = struct_root(doc)
        self.kids_cache = {}
        self.path_cache = {}

    def kids(self, xref):
        cached = self.kids_cache.get(xref)
        if cached is not None:
            return cached
        kind, val = self.doc.xref_get_key(xref, "K")
        out = []
        if kind == "xref":
            out.append(("ref", int(val.split()[0])))
        elif kind == "int":
            out.append(("mcid", int(val)))
        elif kind in ("array", "dict"):
            text = val[1:-1] if kind == "array" else val
            for m in _K_TOKEN.finditer(text):
                if m.group(1) is not None:
                    inner = m.group(1)
                    mcid = re.search(r"/MCID\s+(\d+)", inner)
                    out.append(("mcid", int(mcid.group(1))) if mcid else ("obj", None))
                elif m.group(2) is not None:
                    out.append(("ref", int(m.group(2))))
                else:
                    out.append(("mcid", int(m.group(4))))
        self.kids_cache[xref] = out
        return out

    def resolve(self, path):
        """xref of the element at path, or None if the tree doesn't match."""
        key = tuple((raw, idx) for raw, idx, _ in path)
        if key in self.path_cache:
            return self.path_cache[key]
        node = self.root
        for raw, idx in key:
            kids = self.kids(node) if node is not None else []
            if idx >= len(kids) or kids[idx][0] != "ref":
                node = None
                break
            node = kids[idx][1]
            s = self.doc.xref_get_key(node, "S")
            if s[0] != "name" or s[1][1:] != raw:
                node = None
                break
        self.path_cache[key] = node
        return node

    def actual_text(self, xref):
        kind, val = self.doc.xref_get_key(xref, "ActualText")
        return val if kind == "string" else None


def inject_rolemap(doc):
    """Role-map non-standard struct types to /Div (in memory). Returns count."""
    root = struct_root(doc)
    if root is None:
        return 0
    names = set()
    for xref in range(1, doc.xref_length()):
        try:
            kind, val = doc.xref_get_key(xref, "S")
            if kind != "name" or doc.xref_get_key(xref, "P")[0] != "xref":
                continue
        except Exception:
            continue
        name = val[1:]
        if name and "#" not in name and "/" not in name:
            names.add(name)
    added = 0
    for name in sorted(names - STANDARD):
        if doc.xref_get_key(root, "RoleMap/" + name)[0] == "null":
            doc.xref_set_key(root, "RoleMap/" + name, "/Div")
            added += 1
    return added
