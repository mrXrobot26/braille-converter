"""Review-state file kept next to the source: <name>.<ext>.nassbraille.json.

It stores the (possibly edited) document and which pages were reviewed, so the
helper can close the program and continue later. A changed source file (other
hash) invalidates the saved state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .model import Block, Document, Page

VERSION = 1


def project_path(source):
    source = Path(source)
    return source.with_name(source.name + ".nassbraille.json")


def file_hash(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _block_to_dict(b):
    return {"kind": b.kind, "text": b.text, "bboxes": [list(x) for x in b.bboxes],
            "confidence": b.confidence, "flags": list(b.flags), "box_id": b.box_id}


def _block_from_dict(d):
    return Block(d["kind"], d["text"], [tuple(x) for x in d.get("bboxes", [])],
                 d.get("confidence", 1.0), list(d.get("flags", [])), d.get("box_id"))


def save_project(document, reviewed, path=None):
    """reviewed: set of page numbers marked as reviewed."""
    path = Path(path) if path else project_path(document.source)
    data = {
        "version": VERSION,
        "source": str(document.source),
        "source_sha1": file_hash(document.source),
        "kind": document.kind,
        "report": document.report,
        "pages": [{
            "number": p.number,
            "reviewed": p.number in reviewed,
            "warnings": list(p.warnings),
            "size": list(p.size) if p.size else None,
            "blocks": [_block_to_dict(b) for b in p.blocks],
        } for p in document.pages],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def load_project(source):
    """Returns (Document, reviewed_set) or None if missing/outdated/unreadable."""
    path = project_path(source)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != VERSION or data.get("source_sha1") != file_hash(source):
            return None
        pages, reviewed = [], set()
        for p in data["pages"]:
            pages.append(Page(p["number"], [_block_from_dict(b) for b in p["blocks"]],
                              list(p.get("warnings", [])),
                              tuple(p["size"]) if p.get("size") else None))
            if p.get("reviewed"):
                reviewed.add(p["number"])
        return Document(str(source), data["kind"], pages, data.get("report", {})), reviewed
    except (OSError, ValueError, KeyError, TypeError):
        return None
