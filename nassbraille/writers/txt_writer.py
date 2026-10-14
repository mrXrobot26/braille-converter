"""Write a Document as plain text: one paragraph per line, CRLF line endings."""
from __future__ import annotations

from pathlib import Path

from ..textnorm import TO_WESTERN
from . import marker_text, output_blocks, wants_markers


def document_text(document, opts):
    markers = wants_markers(document, opts)
    lines = []
    for page in document.pages:
        if markers:
            if lines:
                lines.append("")
            lines.append(marker_text(page.number, opts))
        for _, text in output_blocks(page, opts):
            lines.append(text)
    return "\r\n".join(lines) + "\r\n"


def write_txt(document, path, opts):
    """Returns the number of characters the chosen encoding could not hold."""
    text = document_text(document, opts)
    lost = 0
    if opts.txt_encoding.lower() in ("cp1256", "windows-1256"):
        text = text.translate(TO_WESTERN)       # Windows-1256 has no ١٢٣ digits
        lost = sum(1 for ch in text if not _encodable(ch, "cp1256"))
        data = text.encode("cp1256", errors="replace")
    else:
        data = text.encode(opts.txt_encoding)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    return lost


def _encodable(ch, encoding):
    try:
        ch.encode(encoding)
        return True
    except UnicodeEncodeError:
        return False
