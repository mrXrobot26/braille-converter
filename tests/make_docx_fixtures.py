"""Build the synthetic .docx fixtures used by tests/test_docx_in.py.

Each fixture starts from python-docx's default document (styles, numbering,
settings, headers) and gets its body as raw WordprocessingML, so every case
(text boxes with VML fallbacks, merged RTL table cells, numbering overrides,
fields, revisions ...) is spelled out exactly as Word writes it.

    python tests/make_docx_fixtures.py          # writes tests/fixtures/docx/*.docx
"""
from __future__ import annotations

import base64
import io
import itertools
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import XmlPart
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from lxml import etree

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "fixtures" / "docx"

NSDECL = " ".join(f'xmlns:{p}="{u}"' for p, u in (
    ("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main"),
    ("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"),
    ("wp14", "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"),
    ("a", "http://schemas.openxmlformats.org/drawingml/2006/main"),
    ("pic", "http://schemas.openxmlformats.org/drawingml/2006/picture"),
    ("wps", "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"),
    ("wpg", "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"),
    ("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006"),
    ("v", "urn:schemas-microsoft-com:vml"),
    ("o", "urn:schemas-microsoft-com:office:office"),
    ("w10", "urn:schemas-microsoft-com:office:word"),
    ("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
    ("m", "http://schemas.openxmlformats.org/officeDocument/2006/math"),
    ("w14", "http://schemas.microsoft.com/office/word/2010/wordml"),
    ("c", "http://schemas.openxmlformats.org/drawingml/2006/chart"),
    ("dgm", "http://schemas.openxmlformats.org/drawingml/2006/diagram"),
))

_ids = itertools.count(1)   # unique drawing ids (wp:docPr/@id) per process


class Raw(str):
    """A piece of WordprocessingML (plain str arguments are text)."""


def esc(text):
    return escape(text, {'"': "&quot;"})


# -- runs and paragraphs ------------------------------------------------------------
def run(text="", rpr="", content=None):
    inner = content if content is not None else f'<w:t xml:space="preserve">{esc(text)}</w:t>'
    props = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return Raw(f"<w:r>{props}{inner}</w:r>")


def br(kind=None):
    return run(content=f'<w:br w:type="{kind}"/>' if kind else "<w:br/>")


def ppr(style=None, num=None, outline=None, break_before=False, mark_rpr="", sect="",
        frame=""):
    parts = []
    if style:
        parts.append(f'<w:pStyle w:val="{style}"/>')
    if break_before:
        parts.append("<w:pageBreakBefore/>")
    if frame:
        parts.append(frame)
    if num:
        parts.append(f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>')
    parts.append("<w:bidi/>")
    if outline is not None:
        parts.append(f'<w:outlineLvl w:val="{outline}"/>')
    if mark_rpr:
        parts.append(f"<w:rPr>{mark_rpr}</w:rPr>")
    if sect:
        parts.append(sect)
    return "<w:pPr>" + "".join(parts) + "</w:pPr>"


def para(*parts, **kw):
    inner = "".join(p if isinstance(p, Raw) else run(p) for p in parts)
    return Raw(f"<w:p>{ppr(**kw)}{inner}</w:p>")


def body(*items):
    return Raw("".join(i if isinstance(i, Raw) else para(i) for i in items))


# -- tables ---------------------------------------------------------------------------
def cell(*content, merge=None, span=None, fill=None):
    props = ['<w:tcW w:w="2400" w:type="dxa"/>']
    if span:
        props.append(f'<w:gridSpan w:val="{span}"/>')
    if merge == "restart":
        props.append('<w:vMerge w:val="restart"/>')
    elif merge == "continue":
        props.append("<w:vMerge/>")
    if fill:
        props.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>')
    items = [c if isinstance(c, Raw) else para(c) for c in content] or [para()]
    return Raw(f'<w:tc><w:tcPr>{"".join(props)}</w:tcPr>{"".join(items)}</w:tc>')


def row(*cells, header=False):
    cells = [c if isinstance(c, Raw) else cell(c) for c in cells]
    trpr = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
    return Raw(f"<w:tr>{trpr}{''.join(cells)}</w:tr>")


TABLE_BORDERS = "<w:tblBorders>" + "".join(
    f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    for side in ("top", "left", "bottom", "right", "insideH", "insideV")) + "</w:tblBorders>"


def table(*rows, cols=2, rtl=True):
    props = ("<w:tblPr>" + ("<w:bidiVisual/>" if rtl else "") +
             '<w:tblW w:w="0" w:type="auto"/>' + TABLE_BORDERS +
             '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" '
             'w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>')
    grid = "<w:tblGrid>" + '<w:gridCol w:w="2400"/>' * cols + "</w:tblGrid>"
    return Raw(f"<w:tbl>{props}{grid}{''.join(rows)}</w:tbl>")


# -- drawings -------------------------------------------------------------------------
def txbx(*paras):
    return "<w:txbxContent>" + "".join(p if isinstance(p, Raw) else para(p) for p in paras) + \
        "</w:txbxContent>"


def _bodypr(wordart=False):
    art = ' fromWordArt="1"' if wordart else ""
    return (f'<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="91440" tIns="45720" '
            f'rIns="91440" bIns="45720" anchor="t" anchorCtr="0"{art}><a:noAutofit/></wps:bodyPr>')


def _anchor(graphic, y, x, sid, name, cx=1828800, cy=914400):
    return (f'<wp:anchor distT="0" distB="0" distL="114300" distR="114300" simplePos="0" '
            f'relativeHeight="{251658240 + sid}" behindDoc="0" locked="0" layoutInCell="1" '
            f'allowOverlap="1"><wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="column"><wp:posOffset>{x}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="paragraph"><wp:posOffset>{y}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:wrapSquare wrapText="bothSides"/><wp:docPr id="{sid}" name="{name} {sid}"/>'
            f'<wp:cNvGraphicFramePr/>{graphic}</wp:anchor>')


def _inline(graphic, sid, name, cx=914400, cy=914400):
    return (f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{sid}" name="{name} {sid}"/>'
            f'<wp:cNvGraphicFramePr/>{graphic}</wp:inline>')


def _vml_rect(content, y, x, sid):
    return (f'<w:pict><v:rect id="Text Box {sid}" o:spid="_x0000_s{1025 + sid}" '
            f'style="position:absolute;margin-left:{x / 12700:.1f}pt;margin-top:{y / 12700:.1f}pt;'
            f'width:144pt;height:72pt;z-index:{sid}" filled="f" stroked="t">'
            f'<v:textbox>{content}</v:textbox></v:rect></w:pict>')


def box(content, y=0, x=0, wordart=False):
    """A floating text box as Word writes it: wps in mc:Choice, VML in mc:Fallback."""
    sid = next(_ids)
    graphic = (f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/'
               f'wordprocessingShape"><wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr><a:xfrm>'
               f'<a:off x="0" y="0"/><a:ext cx="1828800" cy="914400"/></a:xfrm>'
               f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></wps:spPr>'
               f'<wps:txbx>{content}</wps:txbx>{_bodypr(wordart)}</wps:wsp></a:graphicData>'
               f'</a:graphic>')
    choice = f'<w:drawing>{_anchor(graphic, y, x, sid, "Text Box")}</w:drawing>'
    return run(content=f'<mc:AlternateContent><mc:Choice Requires="wps">{choice}</mc:Choice>'
                       f'<mc:Fallback>{_vml_rect(content, y, x, sid)}</mc:Fallback>'
                       f'</mc:AlternateContent>')


def vml_box(content, y=0, x=0):
    """An old-style VML text box with no DrawingML version."""
    return run(content=_vml_rect(content, y, x, next(_ids)))


def group(children, y=0, x=0):
    """A wpg group of text boxes; children = [(content, child_y, child_x)]."""
    sid = next(_ids)
    shapes, vml = [], []
    for content, cy, cx in children:
        csid = next(_ids)
        shapes.append(
            f'<wps:wsp><wps:cNvPr id="{csid}" name="Text Box {csid}"/><wps:cNvSpPr txBox="1"/>'
            f'<wps:spPr><a:xfrm><a:off x="{cx}" y="{cy}"/><a:ext cx="1828800" cy="457200"/>'
            f'</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></wps:spPr>'
            f'<wps:txbx>{content}</wps:txbx>{_bodypr()}</wps:wsp>')
        vml.append(f'<v:rect style="position:absolute;left:{cx};top:{cy};width:1828800;'
                   f'height:457200"><v:textbox>{content}</v:textbox></v:rect>')
    graphic = (f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/'
               f'wordprocessingGroup"><wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr><a:xfrm>'
               f'<a:off x="0" y="0"/><a:ext cx="1828800" cy="1371600"/><a:chOff x="0" y="0"/>'
               f'<a:chExt cx="1828800" cy="1371600"/></a:xfrm></wpg:grpSpPr>{"".join(shapes)}'
               f'</wpg:wgp></a:graphicData></a:graphic>')
    choice = f'<w:drawing>{_anchor(graphic, y, x, sid, "Group", cy=1371600)}</w:drawing>'
    fallback = (f'<w:pict><v:group id="Group {sid}" style="position:absolute;'
                f'margin-left:{x / 12700:.1f}pt;margin-top:{y / 12700:.1f}pt;width:144pt;'
                f'height:108pt;z-index:{sid}" coordsize="1828800,1371600">{"".join(vml)}'
                f'</v:group></w:pict>')
    return run(content=f'<mc:AlternateContent><mc:Choice Requires="wpg">{choice}</mc:Choice>'
                       f'<mc:Fallback>{fallback}</mc:Fallback></mc:AlternateContent>')


def _pic_graphic(rid, sid):
    return (f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/'
            f'picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="{sid}" name="image{sid}.png"/>'
            f'<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/><a:stretch>'
            f'<a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="914400" cy="914400"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
            f'</a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>')


def inline_picture(rid):
    sid = next(_ids)
    return run(content=f'<w:drawing>{_inline(_pic_graphic(rid, sid), sid, "Picture")}</w:drawing>')


def floating_picture(rid, y=0, x=0):
    sid = next(_ids)
    return run(content='<w:drawing>' + _anchor(_pic_graphic(rid, sid), y, x, sid, "Picture",
                                               cx=914400) + '</w:drawing>')


SHAPETYPE_75 = ('<v:shapetype id="_x0000_t75" coordsize="21600,21600" o:spt="75" '
                'o:preferrelative="t" path="m@4@5l@4@11@9@11@9@5xe" filled="f" stroked="f">'
                '<v:stroke joinstyle="miter"/><v:path o:extrusionok="f" gradientshapeok="t" '
                'o:connecttype="rect"/><o:lock v:ext="edit" aspectratio="t"/></v:shapetype>')


def vml_picture(rid):
    sid = next(_ids)
    return run(content=f'<w:pict>{SHAPETYPE_75}<v:shape id="Picture {sid}" type="#_x0000_t75" '
                       f'style="width:72pt;height:72pt"><v:imagedata r:id="{rid}" o:title=""/>'
                       f'</v:shape></w:pict>')


def picture_with_fallback(rid):
    sid = next(_ids)
    choice = f'<w:drawing>{_inline(_pic_graphic(rid, sid), sid, "Picture")}</w:drawing>'
    fallback = (f'<w:pict>{SHAPETYPE_75}<v:shape id="Picture {sid}" type="#_x0000_t75" '
                f'style="width:72pt;height:72pt"><v:imagedata r:id="{rid}" o:title=""/>'
                f'</v:shape></w:pict>')
    return run(content=f'<mc:AlternateContent><mc:Choice Requires="wps">{choice}</mc:Choice>'
                       f'<mc:Fallback>{fallback}</mc:Fallback></mc:AlternateContent>')


def png_bytes():
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def add_image(doc):
    rid, _ = doc.part.get_or_add_image(io.BytesIO(png_bytes()))
    return rid


# -- complex fields ----------------------------------------------------------------------
def fld(kind):
    return run(content=f'<w:fldChar w:fldCharType="{kind}"/>')


def instr(code):
    return run(content=f'<w:instrText xml:space="preserve">{esc(code)}</w:instrText>')


# -- parts ---------------------------------------------------------------------------------
def add_styles(doc, *xml):
    for item in xml:
        doc.styles.element.append(parse_xml(f'<w:wrap {NSDECL}>{item}</w:wrap>')[0])


def set_numbering(doc, abstracts, nums):
    doc.part.numbering_part._element = parse_xml(
        f'<w:numbering {NSDECL}>{"".join(abstracts)}{"".join(nums)}</w:numbering>')


def add_part(doc, name, content_type, reltype, xml):
    part = XmlPart(PackURI(name), content_type, parse_xml(xml), doc.part.package)
    doc.part.relate_to(part, reltype)
    return part


def lvl(ilvl, fmt, text, start=1, suff=None, legal=False, pstyle=None, restart=None, font=None):
    parts = [f'<w:start w:val="{start}"/>', f'<w:numFmt w:val="{fmt}"/>']
    if restart is not None:
        parts.append(f'<w:lvlRestart w:val="{restart}"/>')
    if pstyle:
        parts.append(f'<w:pStyle w:val="{pstyle}"/>')
    if legal:
        parts.append("<w:isLgl/>")
    if suff:
        parts.append(f'<w:suff w:val="{suff}"/>')
    parts.append(f'<w:lvlText w:val="{esc(text)}"/>')
    parts.append('<w:lvlJc w:val="left"/>')
    parts.append(f'<w:pPr><w:ind w:left="{720 * (ilvl + 1)}" w:hanging="360"/></w:pPr>')
    if font:
        parts.append(f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:hint="default"/></w:rPr>')
    return f'<w:lvl w:ilvl="{ilvl}">{"".join(parts)}</w:lvl>'


def abstract(aid, *levels, style_link=None, num_style_link=None):
    inner = '<w:multiLevelType w:val="hybridMultilevel"/>'
    if style_link:
        inner += f'<w:styleLink w:val="{style_link}"/>'
    if num_style_link:
        inner += f'<w:numStyleLink w:val="{num_style_link}"/>'
    return f'<w:abstractNum w:abstractNumId="{aid}">{inner}{"".join(levels)}</w:abstractNum>'


def num(nid, aid, start_override=None):
    override = ""
    if start_override is not None:
        override = (f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="{start_override}"/>'
                    f'</w:lvlOverride>')
    return f'<w:num w:numId="{nid}"><w:abstractNumId w:val="{aid}"/>{override}</w:num>'


def simple_list(doc, fmt="decimal", text="%1-"):
    set_numbering(doc, [abstract(1, lvl(0, fmt, text))], [num(1, 1)])


# == fixtures ===================================================================================
def fx_textbox(doc):
    return body(
        para("مقدمة الدرس", box(txbx("نص داخل الصندوق", "السطر الثاني"))),
        "فقرة بعد الصندوق",
        para("فقرة فيها صندوق قديم", vml_box(txbx("صندوق بصيغة قديمة"))),
        "نهاية",
    )


def fx_textbox_order(doc):
    return body(
        para("ثلاث صناديق",
             box(txbx("الصندوق السفلي"), y=3000000, x=1000000),
             box(txbx("الصندوق الأيسر"), y=500000, x=1000000),
             box(txbx("الصندوق الأيمن"), y=500000, x=4000000)),
        para("مجموعة", group([(txbx("الثاني في المجموعة"), 900000, 0),
                              (txbx("الأول في المجموعة"), 0, 0)])),
        "نهاية",
    )


def fx_box_colon_list(doc):
    simple_list(doc)
    return body(
        para("أركان الدولة:", box(txbx("ملاحظة: الأركان أربعة"))),
        para("الشعب", num=(1, 0)),
        para("الأرض", num=(1, 0)),
        para("السلطة", num=(1, 0)),
        "فقرة عادية",
        para("- عنصر أول", box(txbx("صندوق بعد القائمة"))),
        "- عنصر ثاني",
        "خاتمة",
        para("سطر عادي فيه صندوق", box(txbx("صندوق عادي"))),
        "آخر سطر",
    )


def fx_tables(doc):
    strong = "<w:b/><w:bCs/>"
    return body(
        "جدول متقسم من اليمين",
        table(
            row(cell("الحضارة المصرية القديمة وبداية الدولة", merge="restart"),
                cell("النهر شريان الحياة في مصر"), cell()),
            row(cell(merge="continue"), cell("الزراعة"), cell("الري")),
            row(cell("التوحيد"), cell("مينا"), cell()),
            cols=3),
        "جدول من صفين",
        table(row("الحاكم", "العصر", "الإنجاز"),
              row("أحمس", "الدولة الحديثة", "طرد الهكسوس"), cols=3),
        "جدول من عمودين",
        table(row("الشعب", "جميع المواطنين"),
              row(cell("الإقليم"), cell("الأرض والحدود", "والمياه الإقليمية")),
              row("السيادة", "استقلال القرار")),
        "جدول له صف عناوين",
        table(row("الثورة", "السنة", "القائد", header=True),
              row("ثورة 1919", "1919", "سعد زغلول"),
              row("ثورة 23 يوليو", "1952", "الضباط الأحرار"), cols=3),
        "جدول جواه جدول",
        table(row(cell("هذه خلية فيها كلام طويل شوية"),
                  cell("خلية ثانية فيها كلام طويل كمان"),
                  cell(table(row("المفتاح", "القيمة المتداخلة")), para())),
              row(cell("سطر أخير في الجدول الخارجي"), cell(), cell()), cols=3),
        "جدول مفاتيح",
        table(row(cell(para(run("العاصمة", strong))), cell("القاهرة")),
              row(cell(para(run("العملة", strong))), cell("الجنيه"))),
        "نهاية الجداول",
    )


def fx_table_in_box(doc):
    content = txbx(para("عنوان الصندوق"),
                   table(row("المكان", "طيبة"), row("الزمان", "الدولة الحديثة"),
                         row("الحدث", "طرد الهكسوس")),
                   para())
    return body(para("صندوق فيه جدول", box(content)), "بعد الصندوق")


def fx_numbering(doc):
    add_styles(
        doc,
        '<w:style w:type="numbering" w:customStyle="1" w:styleId="NassListStyle">'
        '<w:name w:val="Nass List Style"/><w:pPr><w:numPr><w:numId w:val="11"/></w:numPr>'
        '</w:pPr></w:style>',
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="NassQuestion">'
        '<w:name w:val="Nass Question"/><w:basedOn w:val="Normal"/><w:pPr><w:numPr>'
        '<w:numId w:val="12"/></w:numPr><w:bidi/></w:pPr></w:style>',
    )
    set_numbering(doc, [
        abstract(10, lvl(0, "decimal", "%1-"), lvl(1, "decimal", "%1.%2"),
                 lvl(2, "lowerLetter", "(%3)")),
        abstract(11, lvl(0, "arabicAbjad", "%1)")),
        abstract(12, lvl(0, "hindiNumbers", "%1.")),
        abstract(13, lvl(0, "bullet", "\uf0b7", font="Symbol")),
        abstract(14, lvl(0, "decimal", "(%1)", suff="nothing")),
        abstract(15, lvl(0, "arabicAlpha", "%1-", suff="space")),
        abstract(16, lvl(0, "upperRoman", "%1."), lvl(1, "decimal", "%1.%2", legal=True)),
        abstract(17, num_style_link="NassListStyle"),
        abstract(18, lvl(0, "decimal", "%1."), style_link="NassListStyle"),
        abstract(19, lvl(0, "decimal", "س%1:", pstyle="NassQuestion")),
    ], [
        num(1, 10), num(2, 10), num(3, 10, start_override=1), num(4, 11), num(5, 12),
        num(6, 13), num(7, 14), num(8, 15), num(9, 16), num(10, 17), num(11, 18), num(12, 19),
    ])
    return body(
        "قائمة أولى",
        para("البند الأول", num=(1, 0)),
        para("فرع أ", num=(1, 1)),
        para("فرع ب", num=(1, 1)),
        para("تفصيل", num=(1, 2)),
        para("البند الثاني", num=(1, 0)),
        para("فرع بعد الثاني", num=(1, 1)),
        "قائمة تكمل نفس الترقيم",
        para("البند الثالث", num=(2, 0)),
        "قائمة تبدأ من جديد",
        para("بند جديد", num=(3, 0)),
        para("بند جديد ثاني", num=(3, 0)),
        para("أول", num=(4, 0)),
        para("ثاني", num=(4, 0)),
        para("ثالث", num=(4, 0)),
        para("واحد", num=(5, 0)),
        para("اتنين", num=(5, 0)),
        para("نقطة", num=(6, 0)),
        para("نقطة تانية", num=(6, 0)),
        para("ملتصق", num=(7, 0)),
        para("ألف", num=(8, 0)),
        para("باء", num=(8, 0)),
        para("تاء", num=(8, 0)),
        para("باب", num=(9, 0)),
        para("فصل", num=(9, 1)),
        para("مرتبط", num=(10, 0)),
        para("مرتبط تاني", num=(10, 0)),
        para("سؤال", style="NassQuestion"),
        para("سؤال تاني", style="NassQuestion"),
    )


def fx_images(doc):
    rid = add_image(doc)
    return body(
        "قبل الصورة",
        para(inline_picture(rid)),
        "بعد الصورة",
        para("نص وصورة عائمة", floating_picture(rid, y=100000, x=100000)),
        para(vml_picture(rid)),
        para(picture_with_fallback(rid)),
        "آخر",
    )


def fx_charts(doc):
    """Reader-only fixture: the chart, SmartArt and OLE relationship ids are dangling."""
    rid = add_image(doc)
    chart = run(content='<w:drawing>' + _inline(
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        '<c:chart r:id="rId900"/></a:graphicData></a:graphic>', next(_ids), "Chart") +
        '</w:drawing>')
    smartart = run(content='<w:drawing>' + _inline(
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">'
        '<dgm:relIds r:dm="rId901" r:lo="rId902" r:qs="rId903" r:cs="rId904"/></a:graphicData>'
        '</a:graphic>', next(_ids), "Diagram") + '</w:drawing>')
    ole = run(content=f'<w:object w:dxaOrig="300" w:dyaOrig="300">{SHAPETYPE_75}'
                      f'<v:shape id="_x0000_i1025" type="#_x0000_t75" style="width:15pt;height:15pt">'
                      f'<v:imagedata r:id="{rid}" o:title=""/></v:shape>'
                      f'<o:OLEObject Type="Embed" ProgID="Equation.3" ShapeID="_x0000_i1025" '
                      f'DrawAspect="Content" ObjectID="_1234567890" r:id="rId905"/></w:object>')
    wordart = run(content='<w:pict><v:shapetype id="_x0000_t136" coordsize="21600,21600" '
                          'o:spt="136" adj="10800" path="m@7,l@8,m@5,21600l@6,21600e">'
                          '<v:textpath on="t" fitshape="t"/></v:shapetype>'
                          '<v:shape id="WordArt 1" type="#_x0000_t136" style="position:absolute;'
                          'margin-left:0;margin-top:0;width:200pt;height:40pt;z-index:1" '
                          'fillcolor="black"><v:textpath style="font-family:&quot;Arial&quot;" '
                          'string="عنوان فني"/></v:shape></w:pict>')
    modern_art = box(txbx("كلمة فنية حديثة"), wordart=True)
    simple_math = Raw('<m:oMath><m:r><m:t>س=٥</m:t></m:r></m:oMath>')
    fraction = Raw('<m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>2</m:t>'
                   '</m:r></m:den></m:f></m:oMath>')
    return body(
        para("رسم بياني", chart),
        para("سمارت آرت", smartart),
        para("معادلة", ole),
        para(wordart),
        para(modern_art),
        para("المعادلة: ", simple_math),
        para("كسر: ", fraction),
    )


def fx_header_footer(doc):
    section = doc.sections[0]
    section.header.paragraphs[0].text = "ترويسة الصفحة"
    section.footer.paragraphs[0].text = "تذييل الصفحة"
    return body("نص الصفحة الأولى", "نص فيه تعليق")


def after_header_footer(path):
    """Comments go through python-docx's own API once the body exists."""
    doc = Document(str(path))
    target = doc.paragraphs[1].runs[0]
    doc.add_comment(target, text="تعليق المدرس: راجع الفقرة دي", author="مدرس", initials="م")
    doc.save(str(path))


FOOTNOTES_XML = f'''<w:footnotes {NSDECL}>
<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:separator/></w:r></w:p></w:footnote>
<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>
<w:footnote w:id="5"><w:p><w:pPr><w:bidi/></w:pPr><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> تعريف الدولة في الهامش</w:t></w:r></w:p></w:footnote>
<w:footnote w:id="7"><w:p><w:pPr><w:bidi/></w:pPr><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> هامش الصفحة التانية</w:t></w:r></w:p></w:footnote>
</w:footnotes>'''

ENDNOTES_XML = f'''<w:endnotes {NSDECL}>
<w:endnote w:type="separator" w:id="-1"><w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:separator/></w:r></w:p></w:endnote>
<w:endnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r><w:continuationSeparator/></w:r></w:p></w:endnote>
<w:endnote w:id="3"><w:p><w:pPr><w:bidi/></w:pPr><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:endnoteRef/></w:r><w:r><w:t xml:space="preserve"> مصدر في آخر الملف</w:t></w:r></w:p></w:endnote>
</w:endnotes>'''


def note_ref(kind, nid):
    return run(rpr='<w:vertAlign w:val="superscript"/>',
               content=f'<w:{kind}Reference w:id="{nid}"/>')


def fx_footnotes(doc):
    add_part(doc, "/word/footnotes.xml", CT.WML_FOOTNOTES, RT.FOOTNOTES, FOOTNOTES_XML)
    add_part(doc, "/word/endnotes.xml", CT.WML_ENDNOTES, RT.ENDNOTES, ENDNOTES_XML)
    return body(
        para("الدولة", note_ref("footnote", 5), " هي وحدة سياسية"),
        "فقرة تانية في نفس الصفحة",
        para(br("page")),
        para("الصفحة التانية", note_ref("footnote", 7)),
        para("وكمان مصدر", note_ref("endnote", 3)),
    )


def fx_revisions(doc):
    ins = Raw('<w:ins w:id="101" w:author="مدرس" w:date="2026-10-01T10:00:00Z">'
              + run("مضاف") + "</w:ins>")
    dele = Raw('<w:del w:id="102" w:author="مدرس" w:date="2026-10-01T10:00:00Z">'
               '<w:r><w:delText xml:space="preserve">محذوف </w:delText></w:r></w:del>')
    move_from = Raw('<w:moveFrom w:id="103" w:author="مدرس" w:date="2026-10-01T10:00:00Z">'
                    + run("منقول ") + "</w:moveFrom>")
    move_to = Raw('<w:moveTo w:id="104" w:author="مدرس" w:date="2026-10-01T10:00:00Z">'
                  + run("منقول") + "</w:moveTo>")
    gone = Raw('<w:p><w:pPr><w:bidi/><w:rPr><w:del w:id="105" w:author="مدرس" '
               'w:date="2026-10-01T10:00:00Z"/></w:rPr></w:pPr><w:del w:id="106" w:author="مدرس" '
               'w:date="2026-10-01T10:00:00Z"><w:r><w:delText>فقرة اتمسحت كلها</w:delText>'
               '</w:r></w:del></w:p>')
    return body(
        para("نص ", ins, dele, " نهاية"),
        para("قبل ", move_from, "بعد"),
        gone,
        para("هنا ", move_to),
    )


def fx_hidden(doc):
    add_styles(doc, '<w:style w:type="character" w:customStyle="1" w:styleId="NassHidden">'
                    '<w:name w:val="Nass Hidden"/><w:rPr><w:vanish/></w:rPr></w:style>')
    hidden = "<w:vanish/>"
    return body(
        para("ظاهر ", run("مخفي ", hidden), "كمان"),
        para(run("مخفي بالستايل ", '<w:rStyle w:val="NassHidden"/>'), "سطر ظاهر"),
        para(run("فقرة مخفية كلها", hidden), mark_rpr=hidden),
        para(run("مش مخفي", '<w:vanish w:val="0"/>')),
    )


def fx_fields(doc):
    return body(
        para("الصفحة رقم ", fld("begin"), instr(" PAGE "), fld("separate"), run("3"), fld("end")),
        para("زور ", fld("begin"), instr(' HYPERLINK "https://moe.gov.eg" '), fld("separate"),
             run("موقع الوزارة"), fld("end"), " للتفاصيل"),
        para("التاريخ: ", Raw('<w:fldSimple w:instr=" DATE \\@ &quot;d MMMM&quot; ">'
                               + run("١٤ أكتوبر") + "</w:fldSimple>")),
        para("الشرط: ", fld("begin"), instr(" IF "), fld("begin"), instr(" PAGE "),
             fld("separate"), run("9"), fld("end"), instr(' = 9 "نعم" "لا" '), fld("separate"),
             run("نتيجة"), fld("end")),
        para(Raw('<w:hyperlink w:anchor="_top" w:history="1">' + run("رابط عادي")
                 + "</w:hyperlink>")),
    )


def fx_symbols(doc):
    def sym(font, char):
        return run(content=f'<w:sym w:font="{font}" w:char="{char}"/>')
    wingdings = '<w:rFonts w:ascii="Wingdings" w:hAnsi="Wingdings"/>'
    return body(
        para(sym("Symbol", "F0B7"), " بند بنقطة"),
        para(sym("Wingdings", "F0FC"), " صح"),
        para("ألفا ", sym("Symbol", "F061"), " بيتا"),
        para("النبي ", sym("Traditional Arabic", "FDFA")),
        para(run("\uf0d8", wingdings), " سهم"),
        para("ثنائي", run(content="<w:noBreakHyphen/>"), "اللغة وكلمة طويـ",
             run(content="<w:softHyphen/>"), "لة"),
    )


def lrpb(text):
    """A run that Word rendered first on a new page."""
    return run(content=f'<w:lastRenderedPageBreak/><w:t xml:space="preserve">{esc(text)}</w:t>')


def fx_table_pages(doc):
    """Page marks inside tables as Word writes them: a row that runs over onto the
    next page is marked at its split point in some cells and at the start of
    others, and the next row's first cell is marked again."""
    return body(
        "قبل الجدول",
        table(
            row("الصف الأول خلية أولى", "الصف الأول خلية تانية", "الصف الأول خلية تالتة"),
            row(cell(para("الصف التاني ", lrpb("يكمل هنا"))),
                cell(para(lrpb("خلية تانية "), lrpb("تكملتها"))),
                cell(para(lrpb("خلية تالتة")))),
            row(cell(para(lrpb("الصف التالت"))), "خلية ب", "خلية ج"),
            row(cell(para(lrpb("الصف الرابع في صفحة جديدة"))), cell(para(lrpb("خلية د"))),
                cell(para(lrpb("خلية ه")))),
            cols=3),
        "جدول مفاتيح",
        table(row("أ", "قيمة أولى"),
              row(cell("ب"), cell(para("قيمة تانية ", lrpb("تكملتها")))),
              row(cell(para(lrpb("ج"))), "قيمة تالتة")),
        "النهاية",
    )


def fx_broken_field(doc):
    """Reader-only: a field "begin" whose "end" never comes must not hide the text."""
    return body(
        para("قبل الحقل ", fld("begin"), instr(" PAGE "), "نص بعد بداية مكسورة"),
        "النص ده لازم يفضل",
        para("حقل سليم: ", fld("begin"), instr(" PAGE "), fld("separate"), run("٧"), fld("end")),
    )


def fx_sdt(doc):
    block = Raw('<w:sdt><w:sdtPr><w:alias w:val="ملاحظة"/><w:id w:val="11"/></w:sdtPr>'
                '<w:sdtContent>' + para("فقرة جوه أداة محتوى") + '</w:sdtContent></w:sdt>')
    inline = Raw('<w:sdt><w:sdtPr><w:id w:val="12"/><w:text/></w:sdtPr><w:sdtContent>'
                 + run("الاسم") + '</w:sdtContent></w:sdt>')
    custom = Raw('<w:customXml w:uri="urn:nass" w:element="note">'
                 + para("فقرة جوه customXml") + '</w:customXml>')
    return body(block, para("قبل ", inline, " بعد"), custom)


def section(kind=None, size="a4"):
    width, height = (11906, 16838) if size == "a4" else (12240, 15840)
    typ = f'<w:type w:val="{kind}"/>' if kind else ""
    return (f'<w:sectPr>{typ}<w:pgSz w:w="{width}" w:h="{height}"/><w:pgMar w:top="1440" '
            f'w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" '
            f'w:gutter="0"/><w:cols w:space="708"/><w:bidi/></w:sectPr>')


def fx_breaks(doc):
    # sections: 1 (A4) | 2 (Letter, new page) | 3 (Letter, continuous: same page)
    #           | 4 (A4, continuous but a new page size, so Word starts a page anyway)
    return body(
        "الصفحة الأولى",
        para("سطر أول", br(), "سطر تاني"),
        para("آخر الأولى", br("page")),
        para(run(content="<w:lastRenderedPageBreak/><w:t>أول التانية</w:t>")),
        para("الصفحة التالتة", break_before=True),
        para("قبل الكسر", br("page"), "بعد الكسر"),
        para("نهاية القسم", sect=section()),
        "قسم جديد",
        para("عنوان", br(), "بسطرين", style="Heading2"),
        para("نهاية القسم التاني", sect=section(size="letter")),
        para("قسم متصل", sect=section("continuous", size="letter")),
        "مقاس صفحة مختلف",
    )


def remove_styles(doc, *style_ids):
    root = doc.styles.element
    for st in list(root.findall(qn("w:style"))):
        if st.get(qn("w:styleId")) in style_ids:
            root.remove(st)


def fx_headings(doc):
    # Arabic Word keeps the English built-in names but uses its own ids ("1", "a3")
    remove_styles(doc, "Heading1", "Title")
    add_styles(
        doc,
        '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/>'
        '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/>'
        '<w:bidi/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>',
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="2"><w:name w:val="عنوان 2"/>'
        '<w:basedOn w:val="Normal"/><w:rPr><w:b/></w:rPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="a3"><w:name w:val="Title"/>'
        '<w:basedOn w:val="Normal"/><w:rPr><w:sz w:val="48"/></w:rPr></w:style>',
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="NassSub">'
        '<w:name w:val="Nass Subheading"/><w:basedOn w:val="Heading2"/></w:style>',
    )
    return body(
        para("عنوان الكتاب", style="a3"),
        para("الوحدة الأولى", style="1"),
        para("الدرس الأول", style="2"),
        para("أولاً: المفهوم", style="Heading3"),
        para("مستوى عميق", outline=5),
        para("عنوان فرعي مشتق", style="NassSub"),
        # Word ignores a direct outline level on a built-in heading style ...
        para("عنوان رغم مستوى النص", style="1", outline=9),
        # ... but honours it on other styles: body text
        para("نص عادي بستايل مشتق", style="NassSub", outline=9),
        "فقرة عادية",
    )


def fx_legacy_source(doc):
    """Small one-page document that is saved as .doc by Word in the legacy test."""
    simple_list(doc)
    add_part(doc, "/word/footnotes.xml", CT.WML_FOOTNOTES, RT.FOOTNOTES, FOOTNOTES_XML)
    return body(
        para("الدرس الأول", style="Heading1"),
        para("أركان الدولة:"),
        para("الشعب", num=(1, 0)),
        para("الأرض", num=(1, 0)),
        table(row("الحاكم", "أحمس"), row("العصر", "الدولة الحديثة"),
              row("الإنجاز", "طرد الهكسوس")),
        para("الدولة", note_ref("footnote", 5), " هي وحدة سياسية"),
        para("نهاية", box(txbx("صندوق ملاحظة"))),
    )


FIXTURES = {
    "textbox": fx_textbox,
    "textbox_order": fx_textbox_order,
    "box_colon_list": fx_box_colon_list,
    "tables": fx_tables,
    "table_in_box": fx_table_in_box,
    "numbering": fx_numbering,
    "images": fx_images,
    "charts": fx_charts,
    "header_footer": fx_header_footer,
    "footnotes": fx_footnotes,
    "revisions": fx_revisions,
    "hidden": fx_hidden,
    "fields": fx_fields,
    "symbols": fx_symbols,
    "sdt": fx_sdt,
    "breaks": fx_breaks,
    "headings": fx_headings,
    "table_pages": fx_table_pages,
    "broken_field": fx_broken_field,
    "legacy_source": fx_legacy_source,
}
POST = {"header_footer": after_header_footer}
FINAL_SECTION = {"breaks": section("continuous", size="a4")}
# fixtures with dangling relationships that Word itself would refuse to open
READER_ONLY = {"charts", "broken_field"}


def build(name, out_dir):
    doc = Document()
    body_xml = FIXTURES[name](doc)
    sect = doc.element.body.find(qn("w:sectPr"))
    sect_xml = FINAL_SECTION.get(name) or etree.tostring(sect, encoding="unicode")
    doc.part._element = parse_xml(
        f'<w:document {NSDECL} mc:Ignorable="w14 wp14"><w:body>{body_xml}{sect_xml}'
        f'</w:body></w:document>')
    path = Path(out_dir) / f"{name}.docx"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    if name in POST:
        POST[name](path)
    return path


def build_all(out_dir=OUT_DIR):
    return {name: build(name, out_dir) for name in FIXTURES}


# -- Word automation (Windows + Microsoft Word only) -----------------------------------------
_SAVE_AS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
function Decode([string]$b64) { [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($b64)) }
function Call($target, [string]$name, $named) {
    $values = New-Object 'object[]' $named.Count
    $i = 0
    foreach ($v in $named.Values) {
        if ($null -ne $v) { $v = ([psobject]$v).psobject.BaseObject }
        $values[$i] = $v
        $i++
    }
    $result = [System.__ComObject].InvokeMember($name, [Reflection.BindingFlags]::InvokeMethod,
        $null, ([psobject]$target).psobject.BaseObject, $values, $null, $null,
        [string[]]@($named.Keys))
    return ,$result
}
[string]$src = Decode $env:NASS_SRC
[string]$dst = Decode $env:NASS_DST
$word = $null; $doc = $null; $shared = $false
try {
    $word = New-Object -ComObject Word.Application
    $shared = ($word.Documents.Count -gt 0)
    if (-not $shared) { $word.Visible = $false }
    $word.DisplayAlerts = 0
    $documents = $word.Documents
    $doc = Call $documents 'Open' ([ordered]@{ FileName = $src; ConfirmConversions = $false;
        ReadOnly = $true; AddToRecentFiles = $false; Visible = $false })
    Call $doc 'SaveAs2' ([ordered]@{ FileName = $dst; FileFormat = [int]$env:NASS_FORMAT }) | Out-Null
    Call $doc 'Close' ([ordered]@{ SaveChanges = 0 }) | Out-Null
    $doc = $null
    Write-Output 'NASS-OK'
}
finally {
    if ($doc -ne $null) { try { Call $doc 'Close' ([ordered]@{ SaveChanges = 0 }) | Out-Null } catch { } }
    if ($word -ne $null -and -not $shared) { try { Call $word 'Quit' ([ordered]@{ SaveChanges = 0 }) | Out-Null } catch { } }
}
"""


def save_with_word(src, dst, file_format=0):
    """Open `src` in Word and save it as `dst` (0 = .doc 97-2003, 16 = .docx)."""
    def b64(text):
        return base64.b64encode(text.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, NASS_SRC=b64(str(src)), NASS_DST=b64(str(dst)),
               NASS_FORMAT=str(file_format))
    shell = shutil.which("powershell") or "powershell.exe"
    proc = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-EncodedCommand", b64(_SAVE_AS_SCRIPT)],
                          env=env, capture_output=True, timeout=240,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0 or "NASS-OK" not in out or not Path(dst).exists():
        raise RuntimeError("Word could not save %s: %s" % (dst, out.strip()[-400:]))
    return Path(dst)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR
    for fixture, written in build_all(target).items():
        print(fixture, "->", written)
