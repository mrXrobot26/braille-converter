"""Text normalisation that is safe for braille translation.

Letters are never changed: ى/ي, ة/ه and hamza forms stay exactly as decoded,
and the author's typos are kept. Only invisible characters, tatweel,
presentation forms and spacing are normalised.
"""
from __future__ import annotations

import re
import unicodedata

TATWEEL = "ـ"
# bidi controls, zero-width characters, soft hyphen, BOM
INVISIBLE = re.compile("[​-‏؜‪-‮⁦-⁩­﻿]")
# Arabic presentation forms, Latin ligatures, odd spaces and NBSP get NFKC
COMPAT = re.compile("[ﭐ-﷿ﹰ-﻾ﬀ-ﬆ -  ]")
# Compose decomposed hamza/madda letters only. Full NFC is avoided on purpose:
# it reorders harakat (kasra before shadda), and braille writes marks in order.
COMPOSE = (
    ("آ", "آ"),  # alef + madda -> آ
    ("أ", "أ"),  # alef + hamza above -> أ
    ("ؤ", "ؤ"),  # waw + hamza above -> ؤ
    ("إ", "إ"),  # alef + hamza below -> إ
    ("ئ", "ئ"),  # yeh + hamza above -> ئ
)
TO_WESTERN = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
TO_ARABIC = str.maketrans("0123456789۰۱۲۳۴۵۶۷۸۹", "٠١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧٨٩")


def normalize(text):
    """Canonical form of extracted text (no spacing rules yet)."""
    text = COMPAT.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)
    for decomposed, composed in COMPOSE:
        text = text.replace(decomposed, composed)
    text = INVISIBLE.sub("", text).replace(TATWEEL, "")
    return text


PUA = re.compile("[-]")


def clean(text):
    """Final spacing rules, as used for the verified transcription."""
    text = normalize(text)
    # symbol-font glyphs (Wingdings bullets ...) land in the private-use area:
    # a leading one is a bullet, others are decoration
    text = PUA.sub("-", text[:1]) + PUA.sub("", text[1:]) if text else text
    text = re.sub(r"[ \t ]+", " ", text).strip()
    # an Arabic-Indic zero typed as a full stop after a word («آسيا٠»): a
    # braille display would read it as the digit zero
    text = re.sub(r"(?<=[ء-يً-ْ)»]) ?٠(?=\s|$)", ".", text)
    text = re.sub(r" +([،؛:؟!.)»])", r"\1", text)
    text = re.sub(r"([(«]) +", r"\1", text)
    return text


def apply_digits(text, mode):
    if mode == "western":
        return text.translate(TO_WESTERN)
    if mode == "arabic":
        return text.translate(TO_ARABIC)
    return text


# characters a braille translator can be expected to handle
_ALLOWED = set(" .,:;!?()-/\"*'«»،؛؟[]%+=&_–—…")
_ALLOWED |= {chr(c) for c in range(0x0621, 0x063B)}   # hamza .. ghain
_ALLOWED |= {chr(c) for c in range(0x0641, 0x064B)}   # feh .. yeh
_ALLOWED |= {chr(c) for c in range(0x064B, 0x0653)}   # harakat
_ALLOWED |= {chr(c) for c in range(0x0660, 0x066A)}   # Arabic-Indic digits
_ALLOWED |= set("0123456789٪٫٬ٰ")
_ALLOWED |= {chr(c) for c in range(ord("a"), ord("z") + 1)}
_ALLOWED |= {chr(c) for c in range(ord("A"), ord("Z") + 1)}


def odd_chars(text):
    """Characters that may trip a braille translator (for the report)."""
    return sorted({ch for ch in text if ch not in _ALLOWED})


ARABIC_LETTER = re.compile(r"[ء-ي]")


def is_arabic(ch):
    return bool(ARABIC_LETTER.match(ch))
