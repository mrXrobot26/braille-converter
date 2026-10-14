"""Choose, once per font, whether its ToUnicode or the font program is right.

Both readings of all the font's text are scored for "is this real Arabic":
words found in a lexicon built from the document's own reliable text
(ActualText strings, and words both readings agree on), minus impossible
patterns (ة/ى inside a word, reversed lam-alef, a word starting with a mark,
digits glued to letters, private-use characters). The lexicon only picks a
decoder for a whole font; it never changes a word, so typos stay as printed.
"""
from __future__ import annotations

import collections
import re
import unicodedata

from .lines import Token, tokens_text

HARAKAT = re.compile("[ً-ْٰـ]")
WORD_RE = re.compile(r"[^\s،؛؟.,:;!?()\[\]«»\"'\-/]+")
ARABIC = re.compile(r"[ء-ي]")
DIGIT_AI = "٠١٢٣٤٥٦٧٨٩"


def norm_word(w):
    return HARAKAT.sub("", unicodedata.normalize("NFKC", w))


def words_of(text):
    return [norm_word(w) for w in WORD_RE.findall(text) if norm_word(w)]


LEGIT_GLUE = re.compile(r"^([0-9٠-٩]+(م|هـ|ه)|[سج][0-9٠-٩]+|[0-9٠-٩]+[0-9٠-٩٫٬.,/]*)$")


def violations(word):
    if LEGIT_GLUE.match(word):
        return 0          # «١٩١٩م», «س١»: normal in study notes
    v = 0
    if re.search("[ةى].", word):
        v += 1
    if word.startswith(("اأ", "األ", "اال", "اإل", "اآل")):
        v += 1
    if word and unicodedata.category(word[0]) == "Mn":
        v += 1
    if re.search(r"[٠-٩0-9][ء-ي]|[ء-ي][٠-٩0-9]", word):
        v += 1
    if any(0xE000 <= ord(c) <= 0xF8FF or c == "�" for c in word):
        v += 1
    if ARABIC.search(word) and re.search(r"[A-Za-z]", word):
        v += 1
    if re.search("[یکھۀےہ]", word):
        v += 1        # Persian/Urdu letter forms: not used in Arabic study notes
    return v


def glyph_reading(g, info, use_font):
    """(text, from_font) for one glyph under a forced or chosen reading."""
    ft = info.gid_text.get(g.gid) if info.gid_text else None
    if use_font and ft is not None:
        return ft, True
    if ft is not None and g.tu and len(g.tu) == 1 and g.tu.isdigit() and ft and ft.isdigit():
        return ft, True        # digits: the drawn shape decides ١ vs 1
    return g.tu, False


def make_tokens(glyphs, fonts, force=None):
    """force: None (use each font's choice) or (font_key, use_font) for scoring."""
    out = []
    for g in glyphs:
        info = fonts[g.font]
        use_font = info.choice == "font"
        if force is not None and g.font == force[0]:
            use_font = force[1]
        text, from_font = glyph_reading(g, info, use_font)
        space = g.gid in info.space_gids or (text != "" and text.strip() == "")
        if not text and not space:
            continue
        mark = (not space) and all(unicodedata.category(c) in ("Mn", "Me") for c in text)
        adv = g.adv if g.adv > 0 else max(g.bbox[2] - g.bbox[0], 0.0)
        out.append(Token(" " if space else text, g.x, g.x + adv, g.y, g.size,
                         info.space_em, from_font, space, mark, g.seq,
                         (g.bbox[0] + g.bbox[2]) / 2))
    return out


def _font_runs(records, key):
    """Glyphs of one font outside ActualText, grouped per struct leaf and line."""
    for rec in records:
        groups = collections.defaultdict(list)
        for g in rec.glyphs:
            if g.font == key and g.meta is None and g.vis >= 0.5 and not g.invisible:
                groups[(g.path, round(g.y / 3))].append(g)
        yield from groups.values()


def decide_fonts(records, fonts):
    """Set FontInfo.choice for every font; returns a report dict."""
    lexicon = collections.Counter()
    for rec in records:
        for run in rec.metas.values():
            lexicon.update(w for w in words_of(run.text) if len(w) >= 2)
    agreed = collections.Counter()
    runs_by_font = {}
    for info in fonts.fonts:
        info.analyse()
        runs_by_font[info.key] = list(_font_runs(records, info.key))
        for run in runs_by_font[info.key]:
            tu = tokens_text(make_tokens(run, fonts, (info.key, False)))
            fo = tokens_text(make_tokens(run, fonts, (info.key, True)))
            if tu == fo:
                agreed.update(w for w in words_of(tu) if len(w) >= 2)
    lexicon.update(agreed)

    report = {}
    for info in fonts.fonts:
        runs = runs_by_font[info.key]
        glyphs = [g for run in runs for g in run if g.gid not in info.space_gids]
        if not glyphs or not info.gid_text:
            info.choice = "tounicode"
            report[info.name] = {"choice": info.choice, "glyphs": len(glyphs)}
            continue
        covered = sum(1 for g in glyphs if info.gid_text.get(g.gid))
        agree = sum(1 for g in glyphs if info.gid_text.get(g.gid) == g.tu)
        coverage, agreement = covered / len(glyphs), agree / len(glyphs)
        scores, viol_rate = {}, {}
        for use_font in (False, True):
            ws = [w for run in runs
                  for w in words_of(tokens_text(make_tokens(run, fonts, (info.key, use_font))))]
            if not ws:
                scores[use_font], viol_rate[use_font] = 0.0, 0.0
                continue
            long_ws = [w for w in ws if len(w) >= 2] or ws
            hit = sum(1 for w in long_ws if lexicon[w] > 0) / len(long_ws)
            viol = sum(violations(w) for w in ws) / len(ws)
            scores[use_font] = hit - 0.5 * viol
            viol_rate[use_font] = sum(1 for w in ws if violations(w)) / len(ws)
        if agreement >= 0.98:
            info.choice = "tounicode"
        elif coverage >= 0.95 and scores[True] >= scores[False] - 0.02:
            info.choice = "font"
        elif coverage >= 0.6 and scores[True] >= scores[False] + 0.2:
            info.choice = "font"       # clearly better; uncovered glyphs keep ToUnicode
        else:
            info.choice = "tounicode"
        info.scores = {"tounicode": round(scores[False], 3), "font": round(scores[True], 3),
                       "coverage": round(coverage, 3), "agreement": round(agreement, 3),
                       "bad_words": round(viol_rate[info.choice == "font"], 3)}
        report[info.name + f"#{info.key}"] = {"choice": info.choice, "glyphs": len(glyphs),
                                             **info.scores}
    return report


def numeral_mode(records, fonts):
    """'arabic' if Western digits in the text are drawn as Arabic-Indic ones."""
    ai = we = 0
    for rec in records:
        for g in rec.glyphs:
            if g.tu and g.tu in "0123456789" and len(g.tu) == 1:
                ft = fonts[g.font].gid_text.get(g.gid)
                if ft and ft in DIGIT_AI:
                    ai += 1
                elif ft and ft in "0123456789":
                    we += 1
    if ai + we >= 20 and ai >= 0.9 * (ai + we):
        return "arabic", ai, we
    return "printed", ai, we
