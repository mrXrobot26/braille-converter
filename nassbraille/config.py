"""User-facing output options (saved by the GUI between runs)."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class OutputOptions:
    write_docx: bool = True
    write_txt: bool = True
    page_markers: bool = True        # «صفحة N» at the start of every source page
    digits: str = "printed"          # printed | western | arabic
    picture_markers: bool = False    # «(صورة)» where a picture was removed
    txt_encoding: str = "utf-8-sig"  # utf-8-sig | utf-8 | cp1256
    font: str = "Arial"
    base_size: float = 12.5
    line_spacing: float = 1.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)
