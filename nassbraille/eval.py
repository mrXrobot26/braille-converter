"""Measure a reader's output against a verified transcription (markup pages).

usage: python -m nassbraille.eval <file.pdf|docx> <gold_dir> [--pages 2-41] [--worst 8]

Words are compared leniently: letters and digits only, harakat and tatweel
stripped, digits unified. Reported per page and overall:
  recall     share of gold words found in the output (multiset)
  precision  share of output words that are in the gold (multiset)
  order      difflib ratio of the two word sequences
  reachable  recall without gold picture-text lines «(صورة: …)»
"""
from __future__ import annotations

import argparse
import collections
import difflib
import io
import re
import sys
import time
from pathlib import Path

from .model import markup_to_blocks
from .textnorm import TO_ARABIC, clean

HARAKAT = re.compile("[ً-ْٰ]")
WORD = re.compile(r"[ء-ي٠-٩]+|[A-Za-z]+")
MARKER = re.compile(r"^صفحة\s*[0-9٠-٩]+$")


def words(text):
    """Words of the text as it will be written (after textnorm.clean)."""
    text = HARAKAT.sub("", clean(text)).translate(TO_ARABIC)
    return WORD.findall(text)


def gold_page(path):
    """[(kind, words)] per gold line; kind in heading/box/caption/body."""
    out = []
    for block in markup_to_blocks(path.read_text(encoding="utf-8")):
        kind = ("heading" if block.kind.startswith("h") else
                "caption" if block.kind in ("caption", "picture") else
                "box" if block.kind == "box" else "body")
        text = block.text[len("(صورة:"):] if block.text.startswith("(صورة:") else block.text
        out.append((kind, words(text)))
    return out


def output_words(page):
    out = []
    for block in page.blocks:
        if block.kind in ("picture", "notice") or MARKER.match(block.text.strip()):
            continue
        text = block.text.strip()
        text = text[len("(صورة:"):] if text.startswith("(صورة:") else text
        out.extend(words(text))
    return out


def para_integrity(gold_blocks, page):
    """Share of gold paragraphs (>= 4 words) found whole inside one output block."""
    outs = [" ".join(words(b.text)) for b in page.blocks] if page else []
    total = whole = 0
    for kind, ws in gold_blocks:
        if len(ws) < 4 or kind == "caption":
            continue
        total += 1
        needle = " ".join(ws)
        if any(needle in o for o in outs):
            whole += 1
    return whole, total


def heading_match(gold_path, page):
    """(output headings matching a gold heading, output headings,
        gold headings found as headings, gold headings whose words were output)"""
    gold_heads = []
    for block in markup_to_blocks(gold_path.read_text(encoding="utf-8")):
        if block.kind.startswith("h"):
            gold_heads.append(" ".join(words(block.text)))
    out_heads = [" ".join(words(b.text)) for b in (page.blocks if page else [])
                 if b.kind.startswith("h")]
    out_all = " | ".join(" ".join(words(b.text)) for b in (page.blocks if page else []))
    reachable = [g for g in gold_heads if g and g in out_all]
    good_out = sum(1 for o in out_heads if o and any(o == g or o in g or g in o
                                                     for g in gold_heads if g))
    found = sum(1 for g in reachable if any(g == o or g in o or o in g
                                            for o in out_heads if o))
    return good_out, len(out_heads), found, len(reachable)


def page_scores(gold, out):
    g_all = [w for _, ws in gold for w in ws]
    g_reach = [w for kind, ws in gold if kind != "caption" for w in ws]
    gc, oc = collections.Counter(g_all), collections.Counter(out)
    hit = sum((gc & oc).values())
    reach_hit = sum((collections.Counter(g_reach) & oc).values())
    kinds = collections.Counter()
    kinds_hit = collections.Counter()
    pool = collections.Counter(out)
    for kind, ws in gold:
        for w in ws:
            kinds[kind] += 1
            if pool[w] > 0:
                pool[w] -= 1
                kinds_hit[kind] += 1
    order = difflib.SequenceMatcher(None, g_all, out, autojunk=False).ratio() if g_all else 1.0
    return {"gold": len(g_all), "out": len(out), "hit": hit, "reach": len(g_reach),
            "reach_hit": reach_hit, "order": order, "kinds": kinds, "kinds_hit": kinds_hit}


def parse_pages(spec, last):
    if not spec:
        return list(range(1, last + 1))
    pages = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        pages.extend(range(int(a), int(b or a) + 1))
    return pages


def main(argv=None):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("gold")
    ap.add_argument("--pages")
    ap.add_argument("--worst", type=int, default=8)
    ap.add_argument("--show", type=int, default=0, help="print output text of N worst pages")
    ap.add_argument("--no-tags", action="store_true", help="PDF: ignore the struct tree")
    args = ap.parse_args(argv)

    from .convert import read_document
    t0 = time.time()
    if args.no_tags:
        from .pdf.reader import read_pdf
        document = read_pdf(args.source, use_tags=False)
    else:
        document = read_document(args.source)
    elapsed = time.time() - t0
    gold_files = {int(p.stem[1:]): p for p in Path(args.gold).glob("p*.txt")}
    by_number = {p.number: p for p in document.pages}
    pages = [n for n in parse_pages(args.pages, max(gold_files)) if n in gold_files]

    tot = collections.Counter()
    kinds, kinds_hit = collections.Counter(), collections.Counter()
    rows = []
    for n in pages:
        page = by_number.get(n)
        gold = gold_page(gold_files[n])
        s = page_scores(gold, output_words(page) if page else [])
        s["para_whole"], s["para_total"] = para_integrity(gold, page)
        s["h_good"], s["h_out"], s["h_found"], s["h_reach"] = heading_match(gold_files[n], page)
        rows.append((n, s))
        for k in ("gold", "out", "hit", "reach", "reach_hit", "para_whole", "para_total",
                  "h_good", "h_out", "h_found", "h_reach"):
            tot[k] += s[k]
        tot["order"] += s["order"] * s["gold"]
        kinds.update(s["kinds"])
        kinds_hit.update(s["kinds_hit"])

    def pct(a, b):
        return f"{100 * a / b:6.2f}%" if b else "   n/a"

    print(f"read {len(document.pages)} pages in {elapsed:.1f}s")
    print(f"recall {pct(tot['hit'], tot['gold'])}  precision {pct(tot['hit'], tot['out'])}  "
          f"reachable {pct(tot['reach_hit'], tot['reach'])}  "
          f"order {tot['order'] / max(tot['gold'], 1):.3f}  "
          f"paragraphs whole {pct(tot['para_whole'], tot['para_total'])}  (gold words {tot['gold']})")
    print("by kind: " + "  ".join(f"{k} {pct(kinds_hit[k], kinds[k])}" for k in sorted(kinds)))
    print(f"headings: precision {pct(tot['h_good'], tot['h_out'])} ({tot['h_out']} marked)  "
          f"recall {pct(tot['h_found'], tot['h_reach'])} of {tot['h_reach']} readable gold headings")
    rows.sort(key=lambda r: (r[1]["hit"] / r[1]["gold"]) if r[1]["gold"] else 1)
    print("worst pages:")
    for n, s in rows[:args.worst]:
        print(f"  p{n:02d} recall {pct(s['hit'], s['gold'])} precision {pct(s['hit'], s['out'])} "
              f"order {s['order']:.3f} gold {s['gold']}")
    for n, _ in rows[:args.show]:
        page = by_number.get(n)
        print(f"===== p{n:02d} =====")
        for b in (page.blocks if page else []):
            print(f"[{b.kind}] {b.text}")
    return tot


if __name__ == "__main__":
    main()
