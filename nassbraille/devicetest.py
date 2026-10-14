"""Small test files to try once on the braille device, to choose the
defaults (file type, TXT encoding, digit style). ASCII file names, since a
device file browser may not show Arabic names."""
from __future__ import annotations

from pathlib import Path

from .config import OutputOptions
from .model import Block, Document, Page
from .writers.docx_writer import write_docx
from .writers.txt_writer import write_txt

LINES = [
    ("h2", "ملف تجربة لجهاز البرايل"),
    ("para", "١- أرقام عربية: ١٢٣٤٥٦٧٨٩٠ - سنة ١٩٥٢م"),
    ("para", "٢- أرقام إنجليزي: 1234567890 - سنة 1952م"),
    ("para", "٣- تشكيل: كُتِبَ الدَّرْسُ عَلَى السَّبُّورَةِ."),
    ("para", "٤- همزات وحروف: أ إ آ ؤ ئ ء - ى ي - ة ه - لا لأ لإ"),
    ("para", "٥- علامات: (أقواس) و«تنصيص»، وسؤال؟ وتعجب! وفاصلة منقوطة؛ وآخر السطر."),
    ("para", "(أ) بند بحرف"),
    ("para", "س١: لو السطر ده باين صح، يبقى الملف ده مناسب للجهاز؟"),
    ("box", "ده سطر جوه برواز"),
]

VARIANTS = [
    ("test1_word.docx", None),
    ("test2_utf8_bom.txt", "utf-8-sig"),
    ("test3_utf8.txt", "utf-8"),
    ("test4_windows1256.txt", "cp1256"),
]


def write_device_tests(out_dir):
    out_dir = Path(out_dir)
    blocks = [Block(kind, text, box_id=0 if kind == "box" else None) for kind, text in LINES]
    document = Document("device-test.txt", "pdf", [Page(1, blocks)])
    written = []
    for name, encoding in VARIANTS:
        opts = OutputOptions()
        if encoding is None:
            written.append(write_docx(document, out_dir / name, opts))
        else:
            opts.txt_encoding = encoding
            write_txt(document, out_dir / name, opts)
            written.append(out_dir / name)
    return written
