"""Tests for the Word reader (nassbraille.docx_in) and the .doc converter.

The fixtures are built fresh by tests/make_docx_fixtures.py; each one has its
expected reading below as one list of lines per page:

    "# text"     heading (one # per level)
    ">N text"    a line of the N-th text box of the document
    "[صورة]"     a removed picture
    other        a normal paragraph line
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
for _p in (str(ROOT), str(TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import make_docx_fixtures as fx  # noqa: E402
from nassbraille.config import OutputOptions  # noqa: E402
from nassbraille.convert import ConversionError, read_document  # noqa: E402
from nassbraille.doc_legacy import convert_to_docx, word_available  # noqa: E402
from nassbraille.docx_in import read_docx  # noqa: E402
from nassbraille.docx_in.numbering import format_number  # noqa: E402
from nassbraille.docx_in.reader import (WARN_CHART, WARN_EQUATION, WARN_PICTURES,  # noqa: E402
                                        WARN_SMARTART, WARN_SYMBOL)
from nassbraille.model import HEADINGS, PICTURE_MARKER, Document, Page, markup_to_blocks  # noqa: E402
from nassbraille.textnorm import TO_ARABIC, clean  # noqa: E402
from nassbraille.writers.docx_writer import write_docx  # noqa: E402

GOLD = TESTS / "fixtures" / "saifi" / "gold"

EXPECTED = {
    # wps text box in mc:Choice + VML copy in mc:Fallback: read once; VML-only box read
    "textbox": [[
        "مقدمة الدرس", ">1 نص داخل الصندوق", ">1 السطر الثاني", "فقرة بعد الصندوق",
        "فقرة فيها صندوق قديم", ">2 صندوق بصيغة قديمة", "نهاية",
    ]],
    # several boxes in one paragraph: top to bottom, then right to left; group children too
    "textbox_order": [[
        "ثلاث صناديق", ">1 الصندوق الأيمن", ">2 الصندوق الأيسر", ">3 الصندوق السفلي",
        "مجموعة", ">4 الأول في المجموعة", ">5 الثاني في المجموعة", "نهاية",
    ]],
    # a box anchored on a ":" line or a list item waits until the list is over
    "box_colon_list": [[
        "أركان الدولة:", "1- الشعب", "2- الأرض", "3- السلطة", ">1 ملاحظة: الأركان أربعة",
        "فقرة عادية", "- عنصر أول", "- عنصر ثاني", ">2 صندوق بعد القائمة", "خاتمة",
        "سطر عادي فيه صندوق", ">3 صندوق عادي", "آخر سطر",
    ]],
    "tables": [[
        "جدول متقسم من اليمين",
        "الحضارة المصرية القديمة وبداية الدولة", "النهر شريان الحياة في مصر", "الزراعة", "الري",
        "التوحيد", "مينا",
        "جدول من صفين",
        "الحاكم: أحمس", "العصر: الدولة الحديثة", "الإنجاز: طرد الهكسوس",
        "جدول من عمودين",
        "الشعب: جميع المواطنين", "الإقليم: الأرض والحدود", "والمياه الإقليمية",
        "السيادة: استقلال القرار",
        "جدول له صف عناوين",
        "الثورة: ثورة 1919", "السنة: 1919", "القائد: سعد زغلول",
        "الثورة: ثورة 23 يوليو", "السنة: 1952", "القائد: الضباط الأحرار",
        "جدول جواه جدول",
        "هذه خلية فيها كلام طويل شوية", "خلية ثانية فيها كلام طويل كمان",
        "المفتاح: القيمة المتداخلة", "سطر أخير في الجدول الخارجي",
        "جدول مفاتيح",
        "العاصمة: القاهرة", "العملة: الجنيه",
        "نهاية الجداول",
    ]],
    "table_in_box": [[
        "صندوق فيه جدول", ">1 عنوان الصندوق", ">1 المكان: طيبة", ">1 الزمان: الدولة الحديثة",
        ">1 الحدث: طرد الهكسوس", "بعد الصندوق",
    ]],
    # labels checked against Word's own ListFormat.ListString for the same file
    "numbering": [[
        "قائمة أولى", "1- البند الأول", "1.1 فرع أ", "1.2 فرع ب", "(a) تفصيل", "2- البند الثاني",
        "2.1 فرع بعد الثاني", "قائمة تكمل نفس الترقيم", "3- البند الثالث", "قائمة تبدأ من جديد",
        "1- بند جديد", "2- بند جديد ثاني", "أ) أول", "ب) ثاني", "ج) ثالث", "١. واحد", "٢. اتنين",
        "- نقطة", "- نقطة تانية", "(1)ملتصق", "أ- ألف", "ب- باء", "ت- تاء", "I. باب", "1.1 فصل",
        "1. مرتبط", "2. مرتبط تاني", "س1: سؤال", "س2: سؤال تاني",
    ]],
    "images": [[
        "قبل الصورة", "[صورة]", "بعد الصورة", "نص وصورة عائمة", "[صورة]", "[صورة]", "[صورة]",
        "آخر",
    ]],
    "charts": [[
        "رسم بياني", "سمارت آرت", "معادلة", "[صورة]", "عنوان فني", "كلمة فنية حديثة",
        "المعادلة: س=٥", "كسر:",
    ]],
    "header_footer": [["نص الصفحة الأولى", "نص فيه تعليق"]],
    "footnotes": [
        ["الدولة1 هي وحدة سياسية", "فقرة تانية في نفس الصفحة", "1 تعريف الدولة في الهامش"],
        ["الصفحة التانية2", "وكمان مصدرi", "2 هامش الصفحة التانية", "i مصدر في آخر الملف"],
    ],
    "revisions": [["نص مضاف نهاية", "قبل بعد", "هنا منقول"]],
    "hidden": [["ظاهر كمان", "سطر ظاهر", "مش مخفي"]],
    "fields": [[
        "الصفحة رقم 3", "زور موقع الوزارة للتفاصيل", "التاريخ: ١٤ أكتوبر", "الشرط: نتيجة",
        "رابط عادي",
    ]],
    "symbols": [[
        "- بند بنقطة", "- صح", "ألفا بيتا", "النبي صلى الله عليه وسلم", "- سهم",
        "ثنائي-اللغة وكلمة طويلة",
    ]],
    # page marks in tables count per row (checked against Word on a 33-page document)
    "table_pages": [
        ["قبل الجدول", "الصف الأول خلية أولى", "الصف الأول خلية تانية", "الصف الأول خلية تالتة",
         "الصف التاني يكمل هنا", "خلية تانية تكملتها", "خلية تالتة"],
        ["الصف التالت", "خلية ب", "خلية ج"],
        ["الصف الرابع في صفحة جديدة", "خلية د", "خلية ه", "جدول مفاتيح", "أ: قيمة أولى",
         "ب: قيمة تانية تكملتها"],
        ["ج: قيمة تالتة", "النهاية"],
    ],
    "broken_field": [[
        "قبل الحقل نص بعد بداية مكسورة", "النص ده لازم يفضل", "حقل سليم: ٧",
    ]],
    "sdt": [["فقرة جوه أداة محتوى", "قبل الاسم بعد", "فقرة جوه customXml"]],
    # page count agrees with Word's ComputeStatistics for the same file
    "breaks": [
        ["الصفحة الأولى", "سطر أول", "سطر تاني", "آخر الأولى"],
        ["أول التانية"],
        ["الصفحة التالتة", "قبل الكسر"],
        ["بعد الكسر", "نهاية القسم"],
        ["قسم جديد", "## عنوان", "## بسطرين", "نهاية القسم التاني", "قسم متصل"],
        ["مقاس صفحة مختلف"],
    ],
    # outline levels agree with Word's Paragraph.OutlineLevel, except that Title is h1
    # and a style literally named «عنوان 2» counts as a heading here
    "headings": [[
        "# عنوان الكتاب", "# الوحدة الأولى", "## الدرس الأول", "### أولاً: المفهوم",
        "#### مستوى عميق", "## عنوان فرعي مشتق", "# عنوان رغم مستوى النص",
        "نص عادي بستايل مشتق", "فقرة عادية",
    ]],
    "legacy_source": [[
        "# الدرس الأول", "أركان الدولة:", "1- الشعب", "2- الأرض", "الحاكم: أحمس",
        "العصر: الدولة الحديثة", "الإنجاز: طرد الهكسوس", "الدولة1 هي وحدة سياسية", "نهاية",
        ">1 صندوق ملاحظة", "1 تعريف الدولة في الهامش",
    ]],
}

WARNINGS = {
    "images": {WARN_PICTURES},
    "charts": {WARN_CHART, WARN_SMARTART, WARN_PICTURES, WARN_EQUATION},
    "symbols": {WARN_SYMBOL},
}


def view(document):
    """Pages as lists of lines (see the module docstring)."""
    ids, pages = {}, []
    for page in document.pages:
        lines = []
        for block in page.blocks:
            text = clean(block.text)
            if block.kind in HEADINGS:
                lines.append("#" * HEADINGS[block.kind] + " " + text)
            elif block.kind == "box":
                lines.append(">%d %s" % (ids.setdefault(block.box_id, len(ids) + 1), text))
            elif block.kind == "picture":
                lines.append("[صورة]")
            else:
                lines.append(text)
        pages.append(lines)
    return pages


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    return fx.build_all(tmp_path_factory.mktemp("docx_fixtures"))


@pytest.fixture(scope="session")
def documents(built):
    return {name: read_docx(path) for name, path in built.items()}


# -- fixtures ------------------------------------------------------------------------------
def test_every_fixture_has_an_expectation():
    assert set(EXPECTED) == set(fx.FIXTURES)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_reading(name, documents):
    assert view(documents[name]) == EXPECTED[name]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_warnings(name, documents):
    found = {w for page in documents[name].pages for w in page.warnings}
    assert found == WARNINGS.get(name, set())


def test_document_shape(documents, built):
    doc = documents["footnotes"]
    assert doc.kind == "docx"
    assert doc.source == str(built["footnotes"])
    assert [p.number for p in doc.pages] == [1, 2]
    assert all(b.kind == "para" for b in doc.pages[0].blocks)
    assert doc.report["footnotes"] == 2 and doc.report["endnotes"] == 1


def test_raw_text_is_kept(documents):
    raw = [b.text for b in documents["symbols"].pages[0].blocks]
    assert "النبي \ufdfa" in raw          # letters stay as stored; writers clean later
    raw = [b.text for b in documents["numbering"].pages[0].blocks]
    assert "(1)ملتصق" in raw              # w:suff="nothing"
    assert "1- البند الأول" in raw        # w:suff tab -> one space


def test_picture_blocks(documents):
    pictures = [b for b in documents["images"].pages[0].blocks if b.kind == "picture"]
    assert len(pictures) == 4
    assert all(b.text == PICTURE_MARKER for b in pictures)


def test_box_ids(documents):
    blocks = documents["textbox"].pages[0].blocks
    boxes = [b for b in blocks if b.kind == "box"]
    assert len({b.box_id for b in boxes}) == 2
    assert boxes[0].box_id == boxes[1].box_id
    assert all(b.box_id is None for b in blocks if b.kind != "box")


def test_progress_is_reported(built):
    calls = []
    read_docx(built["tables"], progress=lambda done, total, msg: calls.append((done, total, msg)))
    assert calls and calls[-1][0] == calls[-1][1]
    assert all(isinstance(m, str) and m for _, _, m in calls)


def test_read_document_entry_point(built):
    doc = read_document(built["headings"])
    assert doc.kind == "docx" and view(doc) == EXPECTED["headings"]


def test_not_a_word_file(tmp_path):
    bad = tmp_path / "مش وورد.docx"
    bad.write_bytes(b"this is not a zip file")
    with pytest.raises(ConversionError):
        read_docx(bad)


def test_protected_or_old_file_message(tmp_path, monkeypatch):
    from nassbraille import doc_legacy

    def cannot_convert(path):
        raise ConversionError("conversion failed")

    monkeypatch.setattr(doc_legacy, "convert_to_docx", cannot_convert)
    locked = tmp_path / "عليه باسورد.docx"
    locked.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 512)
    with pytest.raises(ConversionError) as info:
        read_docx(locked)
    assert "كلمة سر" in str(info.value)


# -- number formats --------------------------------------------------------------------------
@pytest.mark.parametrize("n, fmt, expected", [
    (7, "decimal", "7"),
    (7, "decimalZero", "07"),
    (12, "decimalZero", "12"),
    (3, "upperLetter", "C"),
    (28, "lowerLetter", "bb"),
    (14, "upperRoman", "XIV"),
    (9, "lowerRoman", "ix"),
    (1, "arabicAlpha", "أ"), (3, "arabicAlpha", "ت"), (28, "arabicAlpha", "ي"),
    (1, "arabicAbjad", "أ"), (3, "arabicAbjad", "ج"), (10, "arabicAbjad", "ي"),
    (28, "arabicAbjad", "غ"),
    (12, "hindiNumbers", "١٢"),
    (4, "bullet", "-"),
    (4, "none", ""),
    (5, "custom", "5"),
])
def test_format_number(n, fmt, expected):
    assert format_number(n, fmt) == expected


def test_custom_zero_padded_format():
    assert format_number(7, "custom", "001, 002, 003, ...") == "007"


# -- end to end: the verified Saifi transcription through the Word writer and back ------------
def gold_document():
    pages = []
    for n in range(1, 59):
        text = (GOLD / f"p{n:02d}.txt").read_text(encoding="utf-8")
        pages.append(Page(number=n, blocks=markup_to_blocks(text)))
    return Document(source=str(GOLD / "saifi.pdf"), kind="pdf", pages=pages)


@pytest.mark.skipif(not GOLD.exists(), reason="local verified transcription not present")
def test_gold_round_trip(tmp_path):
    gold = gold_document()
    out = tmp_path / "saifi.docx"
    write_docx(gold, out, OutputOptions())
    back = read_docx(out)
    assert len(back.pages) == len(gold.pages) == 58
    for src, got in zip(gold.pages, back.pages):
        # the writer starts every page with a «صفحة N» marker paragraph and drops
        # picture markers (OutputOptions.picture_markers is off by default)
        expected = ["صفحة " + str(src.number).translate(TO_ARABIC)]
        kinds = ["para"]
        for block in src.blocks:
            if block.kind == "picture" or not clean(block.text):
                continue
            expected.append(clean(block.text))
            kinds.append(block.kind if block.kind in HEADINGS else "para")
        assert [clean(b.text) for b in got.blocks] == expected, f"page {src.number}"
        assert [b.kind for b in got.blocks] == kinds, f"page {src.number}"


# -- .doc through Microsoft Word ---------------------------------------------------------------
needs_word = pytest.mark.skipif(not word_available(), reason="Microsoft Word is not installed")


@needs_word
def test_doc_via_word(tmp_path, built):
    folder = tmp_path / "ملفات قديمة للتجربة"
    folder.mkdir()
    doc_path = folder / "مذكرة التاريخ القديمة.doc"
    fx.save_with_word(built["legacy_source"], doc_path, file_format=0)
    assert doc_path.read_bytes()[:4] == b"\xd0\xcf\x11\xe0"     # a real Word 97-2003 file
    converted = convert_to_docx(doc_path)
    assert converted.suffix == ".docx" and converted.exists()
    assert view(read_docx(converted)) == EXPECTED["legacy_source"]
    document = read_document(doc_path)
    assert document.source == str(doc_path)
    assert view(document) == EXPECTED["legacy_source"]
    # the same old file renamed to .docx (Word opens those without a word)
    renamed = folder / "متسمي غلط.docx"
    renamed.write_bytes(doc_path.read_bytes())
    document = read_document(renamed)
    assert document.source == str(renamed)
    assert view(document) == EXPECTED["legacy_source"]


def test_convert_missing_file(tmp_path):
    with pytest.raises(ConversionError):
        convert_to_docx(tmp_path / "مش موجود.doc")


def test_convert_falls_back_to_libreoffice(tmp_path, monkeypatch, built):
    from nassbraille import doc_legacy

    def word_fails(src, dst, work):
        raise RuntimeError("no Word")

    def libreoffice(src, dst, work):
        assert src.name == "source.rtf" and src.read_bytes() == b"{\\rtf1 x}"
        dst.write_bytes(built["textbox"].read_bytes())

    monkeypatch.setattr(doc_legacy, "_convert_with_word", word_fails)
    monkeypatch.setattr(doc_legacy, "_convert_with_libreoffice", libreoffice)
    source = tmp_path / "ملف قديم.rtf"
    source.write_bytes(b"{\\rtf1 x}")
    assert view(read_docx(convert_to_docx(source))) == EXPECTED["textbox"]


def test_convert_without_any_converter(tmp_path, monkeypatch):
    from nassbraille import doc_legacy

    def fails(src, dst, work):
        raise RuntimeError("missing")

    monkeypatch.setattr(doc_legacy, "_convert_with_word", fails)
    monkeypatch.setattr(doc_legacy, "_convert_with_libreoffice", fails)
    source = tmp_path / "ملف.doc"
    source.write_bytes(b"\xd0\xcf\x11\xe0 not really")
    with pytest.raises(ConversionError) as info:
        convert_to_docx(source)
    assert "docx" in str(info.value)
