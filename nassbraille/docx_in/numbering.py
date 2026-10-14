"""List numbering: the label Word prints in front of a numbered paragraph.

NumberingResolver.label_for(p) must be called once per paragraph, in document
order, because it advances the list counters.

* numPr comes from the paragraph or its style chain; abstractNums that only
  point to a numbering style (numStyleLink) are followed to the abstractNum
  carrying the matching styleLink.
* The level definition comes from the num's lvlOverride, else the abstractNum.
* Counters are kept per abstractNum. A startOverride applies on the first use
  of that numId. Using a level resets the deeper levels, subject to lvlRestart.
* lvlText "%1".."%9" are replaced with each level's value in its numFmt;
  isLgl forces decimal; w:suff tab/space -> " ", nothing -> "".
"""
from __future__ import annotations

import re

from .ns import W, attr, children, int_val, on_off, val
from .styles import StyleSheet

ARABIC_ALPHA = "أبتثجحخدذرزسشصضطظعغفقكلمنهوي"
ARABIC_ABJAD = "أبجدهوزحطيكلمنسعفصقرشتثخذضظغ"
TO_ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
ROMAN = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
         (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
BULLET_LABEL = "-"
PLACEHOLDER = re.compile(r"%([1-9])")
CUSTOM_DIGITS = re.compile(r"^\s*([0-9٠-٩]+)\s*$")

W_NUM = W + "num"
W_ABSTRACT = W + "abstractNum"
W_LVL = W + "lvl"
W_PPR = W + "pPr"
W_NUMPR = W + "numPr"
W_NUMID = W + "numId"
W_ILVL = W + "ilvl"


def _letters(n, alphabet):
    if n <= 0:
        return str(n)
    size = len(alphabet)
    return alphabet[(n - 1) % size] * ((n - 1) // size + 1)


def _roman(n):
    if n <= 0 or n >= 4000:
        return str(n)
    out = []
    for value, letters in ROMAN:
        while n >= value:
            out.append(letters)
            n -= value
    return "".join(out)


def format_number(n, fmt, custom=None):
    """Number `n` in the w:numFmt `fmt` ("decimal", "arabicAbjad", ...)."""
    fmt = fmt or "decimal"
    if fmt == "decimal":
        return str(n)
    if fmt == "decimalZero":
        return "%02d" % n if 0 <= n < 10 else str(n)
    if fmt == "upperLetter":
        return _letters(n, "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if fmt == "lowerLetter":
        return _letters(n, "abcdefghijklmnopqrstuvwxyz")
    if fmt == "upperRoman":
        return _roman(n)
    if fmt == "lowerRoman":
        return _roman(n).lower()
    if fmt == "arabicAlpha":
        return _letters(n, ARABIC_ALPHA)
    if fmt == "arabicAbjad":
        return _letters(n, ARABIC_ABJAD)
    if fmt == "hindiNumbers":
        return str(n).translate(TO_ARABIC_INDIC)
    if fmt == "decimalEnclosedFullstop":
        return "%d." % n
    if fmt == "decimalEnclosedParen":
        return "(%d)" % n
    if fmt == "bullet":
        return BULLET_LABEL
    if fmt == "none":
        return ""
    if fmt == "chicago":                     # footnote marks * † ‡ §
        return _letters(n, "*†‡§")
    if fmt == "custom" and custom:
        first = custom.split(",")[0]
        m = CUSTOM_DIGITS.match(first)
        if m:
            digits = m.group(1)
            text = str(n).rjust(len(digits), "0")
            if digits[0] in "٠١٢٣٤٥٦٧٨٩":
                text = text.translate(TO_ARABIC_INDIC)
            return text
    # ordinal, cardinalText, decimalEnclosedCircle, East Asian counting, ...:
    # the plain number keeps the information without inventing words
    return str(n)


class _Level:
    """The parts of a w:lvl the label needs."""

    __slots__ = ("start", "fmt", "custom", "text", "suffix", "legal", "restart", "pstyle")

    def __init__(self, el):
        self.start = int_val(el.find(W + "start"), 0)
        self.fmt, self.custom = "decimal", None
        for ch in children(el):             # w:numFmt may sit in mc:AlternateContent
            if ch.tag == W + "numFmt":
                self.fmt = val(ch, "decimal")
                self.custom = attr(ch, "format")
                break
        text_el = el.find(W + "lvlText")
        self.text = val(text_el, "") if text_el is not None else ""
        suff = val(el.find(W + "suff"), "tab")
        self.suffix = "" if suff == "nothing" else " "
        self.legal = bool(on_off(el.find(W + "isLgl")))
        restart = el.find(W + "lvlRestart")
        self.restart = int_val(restart) if restart is not None else None
        self.pstyle = val(el.find(W + "pStyle"))


class _Counters:
    __slots__ = ("values", "pending")

    def __init__(self):
        self.values = [None] * 9
        self.pending = {}


class NumberingResolver:
    def __init__(self, numbering_root=None, styles=None):
        if not isinstance(styles, StyleSheet):
            styles = StyleSheet(styles)
        self.styles = styles
        self.nums = {}
        self.abstracts = {}
        if numbering_root is not None:
            for el in children(numbering_root):
                if el.tag == W_ABSTRACT:
                    key = _int(attr(el, "abstractNumId"))
                    if key is not None:
                        self.abstracts.setdefault(key, el)
                elif el.tag == W_NUM:
                    key = _int(attr(el, "numId"))
                    if key is not None:
                        self.nums.setdefault(key, el)
        self._counters = {}
        self._seen_nums = set()
        self._levels = {}

    # -- public -----------------------------------------------------------------
    def numpr_for(self, p):
        """(numId, ilvl) of a paragraph, or None when it is not numbered."""
        ppr = p.find(W_PPR)
        num_id = ilvl = None
        if ppr is not None:
            numpr = ppr.find(W_NUMPR)
            if numpr is not None:
                num_id = int_val(numpr.find(W_NUMID))
                ilvl = int_val(numpr.find(W_ILVL))
        style_id = self.styles.para_style_id(p)
        if num_id is None:
            for st in self.styles.chain(style_id):
                sppr = st.find(W_PPR)
                numpr = sppr.find(W_NUMPR) if sppr is not None else None
                if numpr is None:
                    continue
                if ilvl is None:
                    ilvl = int_val(numpr.find(W_ILVL))
                num_id = int_val(numpr.find(W_NUMID))
                if num_id is not None:
                    break
        if not num_id or num_id not in self.nums:
            return None
        if ilvl is None:
            ilvl = self._style_level(num_id, style_id)
        return num_id, max(0, min(int(ilvl), 8))

    def label_for(self, p):
        """The printed list label (with its suffix space), or "" when none."""
        info = self.numpr_for(p)
        if info is None:
            return ""
        num_id, ilvl = info
        num = self.nums[num_id]
        abs_id = self._abstract_id(num)
        if abs_id is None:
            return ""
        state = self._counters.setdefault(abs_id, _Counters())
        if num_id not in self._seen_nums:
            self._seen_nums.add(num_id)
            for lvl_no, start in self._start_overrides(num).items():
                state.pending[lvl_no] = start
        level = self._level(num_id, abs_id, ilvl)
        if level is None:
            return ""
        if ilvl in state.pending:
            value = state.pending.pop(ilvl)
        elif state.values[ilvl] is None:
            value = level.start
        else:
            value = state.values[ilvl] + 1
        state.values[ilvl] = value
        for deeper in range(ilvl + 1, 9):
            dl = self._level(num_id, abs_id, deeper)
            restart = dl.restart if dl is not None else None
            if restart is None or restart - 1 >= deeper:
                state.values[deeper] = None          # default: any higher level resets
            elif restart != 0 and ilvl < restart:
                state.values[deeper] = None
        return self._render(num_id, abs_id, level, state)

    # -- internals ----------------------------------------------------------------
    def _render(self, num_id, abs_id, level, state):
        if level.fmt == "none":
            return ""
        if level.fmt == "bullet":
            return BULLET_LABEL + level.suffix

        def substitute(m):
            k = int(m.group(1)) - 1
            lk = self._level(num_id, abs_id, k)
            if lk is None:
                return ""
            value = state.values[k]
            if value is None:
                value = lk.start
            if lk.fmt == "none":
                return ""
            if level.legal and lk.fmt != "bullet":
                return str(value)
            return format_number(value, lk.fmt, lk.custom)

        text = PLACEHOLDER.sub(substitute, level.text)
        if not text.strip():
            return ""
        return text + level.suffix

    def _abstract_id(self, num, depth=0):
        abs_id = int_val(num.find(W + "abstractNumId"))
        abstract = self.abstracts.get(abs_id)
        if abstract is None:
            return None
        link = val(abstract.find(W + "numStyleLink"))
        if link is None or depth > 4:
            return abs_id
        # numbering style -> its numId -> the abstractNum that defines the levels
        for st in self.styles.chain(link):
            sppr = st.find(W_PPR)
            numpr = sppr.find(W_NUMPR) if sppr is not None else None
            linked = int_val(numpr.find(W_NUMID)) if numpr is not None else None
            if linked in self.nums and self.nums[linked] is not num:
                target = self._abstract_id(self.nums[linked], depth + 1)
                if target is not None:
                    return target
        for key, other in self.abstracts.items():
            if val(other.find(W + "styleLink")) == link:
                return key
        return abs_id

    def _level(self, num_id, abs_id, ilvl):
        key = (num_id, abs_id, ilvl)
        if key in self._levels:
            return self._levels[key]
        el = None
        num = self.nums.get(num_id)
        if num is not None:
            for ov in num.findall(W + "lvlOverride"):
                if _int(attr(ov, "ilvl")) == ilvl:
                    el = ov.find(W_LVL)
                    break
        if el is None:
            abstract = self.abstracts.get(abs_id)
            if abstract is not None:
                for lvl in abstract.findall(W_LVL):
                    if _int(attr(lvl, "ilvl")) == ilvl:
                        el = lvl
                        break
        level = _Level(el) if el is not None else None
        self._levels[key] = level
        return level

    def _start_overrides(self, num):
        out = {}
        for ov in num.findall(W + "lvlOverride"):
            ilvl = _int(attr(ov, "ilvl"))
            start = ov.find(W + "startOverride")
            if ilvl is None or not 0 <= ilvl <= 8:
                continue
            if start is not None:
                out[ilvl] = int_val(start, 0)
            else:
                lvl = ov.find(W_LVL)
                if lvl is not None and lvl.find(W + "start") is not None:
                    out[ilvl] = int_val(lvl.find(W + "start"), 0)
        return out

    def _style_level(self, num_id, style_id):
        """Level whose w:pStyle is the paragraph's style (style-linked lists)."""
        abs_id = self._abstract_id(self.nums[num_id])
        if abs_id is None or style_id is None:
            return 0
        for ilvl in range(9):
            level = self._level(num_id, abs_id, ilvl)
            if level is not None and level.pstyle == style_id:
                return ilvl
        return 0


def _int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None
