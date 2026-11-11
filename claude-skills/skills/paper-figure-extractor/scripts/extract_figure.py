#!/usr/bin/env python3
"""Find the figures of a paper PDF and crop one out at high resolution.

The region of a figure is computed from the PDF itself: the caption ("Figure 3:")
is located in the text layer, and the box is the union of the drawings, images and
labels that sit next to it. Nothing is guessed from a rendered picture.

    extract_figure.py list    paper.pdf [--tables]
    extract_figure.py preview paper.pdf --page 3 --out page3.png
    extract_figure.py crop    paper.pdf --figure 2 --out fig.png [--dpi 600] [--vector]
    extract_figure.py crop    paper.pdf --table 1  --out tab.png
    extract_figure.py crop    paper.pdf --page 3 --bbox 72,90,540,310 --out fig.png

list     JSON with every figure: number, page, caption, bbox, and a confidence note.
preview  the page as a PNG with each detected box drawn and labelled, for checking.
crop     the region as a PNG (default 600 DPI). --vector also writes a .pdf next to
         it that keeps vector graphics as vectors. --bbox overrides the detected box;
         it is x0,y0,x1,y1 in PDF points with the origin at the top-left of the page,
         the same units `list` prints.

Requires PyMuPDF (run with the project's .venv/bin/python).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:  # older installs
    try:
        import fitz as pymupdf
    except ImportError:
        sys.exit("PyMuPDF is not installed. Run ./setup.sh in the project root and use .venv/bin/python.")

CAPTION = re.compile(r"^\s*(Figure|Fig\.?|Table|Tab\.?)\s*~?\s*(S?\d+|[A-Z]\.?\d+)\s*([:.|]|—|-)", re.I)
PAD = 4.0          # points of white space kept around the crop
NEAR = 14.0        # an element this close to the growing box belongs to it
MAX_PIXELS = 9000  # longest side of the PNG; DPI is lowered beyond this


# ------------------------------------------------------------------ page elements

def text_blocks(page) -> list[dict]:
    """Text blocks with their box, text, line count and dominant font size."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        lines = [ln for ln in b["lines"] if any(s["text"].strip() for s in ln["spans"])]
        if not lines:
            continue
        sizes: dict[float, int] = {}
        text_lines = []
        for ln in lines:
            text_lines.append("".join(s["text"] for s in ln["spans"]))
            for s in ln["spans"]:
                sizes[round(s["size"], 1)] = sizes.get(round(s["size"], 1), 0) + len(s["text"])
        out.append({
            "rect": pymupdf.Rect(b["bbox"]),
            "text": " ".join(t.strip() for t in text_lines).strip(),
            "lines": len(lines),
            "size": max(sizes, key=sizes.get),
            "horizontal": all(abs(ln["dir"][1]) < 0.1 for ln in lines),
        })
    return out


def body_font_size(doc) -> float:
    """The font size most of the running text is set in."""
    sizes: dict[float, int] = {}
    for page in list(doc)[:12]:
        for b in text_blocks(page):
            if b["lines"] >= 3:
                sizes[b["size"]] = sizes.get(b["size"], 0) + len(b["text"])
    return max(sizes, key=sizes.get) if sizes else 10.0


def graphics(page) -> list:
    """Boxes of vector drawings and raster images, minus page furniture."""
    pr = page.rect
    top, bottom = pr.y0 + 0.07 * pr.height, pr.y1 - 0.05 * pr.height
    rects = []
    for d in page.get_drawings():
        rects.append(pymupdf.Rect(d["rect"]))
    for im in page.get_image_info():
        rects.append(pymupdf.Rect(im["bbox"]))
    keep = []
    for r in rects:
        r = r & pr
        if r.is_empty and r.width < 0.5 and r.height < 0.5:
            continue
        if r.width * r.height > 0.85 * pr.width * pr.height:   # page background
            continue
        if r.y1 < top or r.y0 > bottom:                          # header / footer rules
            continue
        keep.append(r)
    return keep


def is_paragraph(block: dict, body: float, col_width: float) -> bool:
    """Running text of the paper (as opposed to labels inside a figure)."""
    if not block["horizontal"] or abs(block["size"] - body) > 0.6:
        return False
    wide = block["rect"].width >= 0.6 * col_width
    return (block["lines"] >= 3 and wide) or (block["lines"] >= 2 and wide and len(block["text"]) > 150)


def h_overlap(a, b) -> float:
    return max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))


# ------------------------------------------------------------------ detection

def find_captions(page, blocks) -> list[dict]:
    caps = []
    for b in blocks:
        m = CAPTION.match(b["text"])
        if not m or not b["horizontal"]:
            continue
        kind = "table" if m.group(1).lower().startswith("tab") else "figure"
        caps.append({"kind": kind, "number": m.group(2).rstrip("."), "block": b, "rect": b["rect"]})
    return caps


def region_for(cap: dict, page, blocks, caps, gfx, body: float, side: str):
    """Box of the figure belonging to `cap`, looking above ('up') or below ('down') the caption."""
    pr = page.rect
    crect = cap["rect"]
    margin_top, margin_bottom = pr.y0 + 0.07 * pr.height, pr.y1 - 0.05 * pr.height
    col_width = max(crect.width, 0.38 * pr.width)

    paragraphs = [b for b in blocks if b is not cap["block"] and is_paragraph(b, body, col_width)]
    others = [c["rect"] for c in caps if c is not cap]
    # Things that end a figure: running text and other captions in the caption's column.
    stops = [p["rect"] for p in paragraphs if h_overlap(p["rect"], crect) > 0.3 * min(p["rect"].width, crect.width)]
    stops += [r for r in others if h_overlap(r, crect) > 0.3 * min(r.width, crect.width)]

    if side == "up":
        limit = max([r.y1 for r in stops if r.y1 <= crect.y0 + 2] + [margin_top])
        lo, hi = limit, crect.y0
    else:
        limit = min([r.y0 for r in stops if r.y0 >= crect.y1 - 2] + [margin_bottom])
        lo, hi = crect.y1, limit
    if hi - lo < 12:
        return None, 0

    def inside(r) -> bool:
        return r.y0 >= lo - 2 and r.y1 <= hi + 2

    def claimed_by_other(r) -> bool:
        """Sits over a neighbouring caption rather than ours (figures side by side)."""
        mine = h_overlap(r, crect)
        for o in others:
            near_same_row = abs(o.y0 - crect.y0) < 0.25 * pr.height
            if near_same_row and h_overlap(r, o) > mine and h_overlap(r, o) > 0.5 * r.width:
                return True
        return False

    para_rects = [p["rect"] for p in paragraphs]
    labels = [b["rect"] for b in blocks
              if b is not cap["block"] and b["rect"] not in para_rects and not CAPTION.match(b["text"])]
    pool = [r for r in gfx if inside(r) and not claimed_by_other(r)]
    label_pool = [r for r in labels if inside(r) and not claimed_by_other(r)]

    seed = [r for r in pool if h_overlap(r, crect) > 0]
    if not seed:
        return None, 0
    box = pymupdf.Rect(seed[0])
    for r in seed[1:]:
        box |= r
    used = len(seed)
    remaining = [r for r in pool if r not in seed] + label_pool
    grew = True
    while grew:                      # absorb neighbours: sub-figures, axis labels, legends
        grew = False
        reach = pymupdf.Rect(box.x0 - NEAR, box.y0 - NEAR, box.x1 + NEAR, box.y1 + NEAR)
        for r in list(remaining):
            if not reach.intersects(r):
                continue
            trial = box | r
            if any(trial.intersects(p) and not box.intersects(p) for p in para_rects):
                continue             # growing this way would swallow running text
            box, grew = trial, True
            remaining.remove(r)
            used += 1
    box = pymupdf.Rect(box.x0 - PAD, max(box.y0 - PAD, lo - PAD), box.x1 + PAD, min(box.y1 + PAD, hi + PAD)) & pr
    return box, used


def detect(doc, include_tables: bool = False) -> list[dict]:
    body = body_font_size(doc)
    found = []
    for pno, page in enumerate(doc, 1):
        blocks = text_blocks(page)
        caps = find_captions(page, blocks)
        if not caps:
            continue
        gfx = graphics(page)
        for cap in caps:
            if cap["kind"] == "table" and not include_tables:
                continue
            order = ("down", "up") if cap["kind"] == "table" else ("up", "down")
            best, note = None, ""
            for side in order:
                box, used = region_for(cap, page, blocks, caps, gfx, body, side)
                if box is not None and box.height > 20 and box.width > 30:
                    best = box
                    note = "" if side == order[0] else f"content found {'below' if side == 'down' else 'above'} the caption"
                    break
            if best is None and cap["kind"] == "table":
                # Tables set without rules have no drawings: take the text between caption and next paragraph.
                best = table_text_region(cap, page, blocks, caps, body)
                note = "table without rules; box taken from text rows" if best is not None else ""
            entry = {
                "kind": cap["kind"],
                "number": cap["number"],
                "page": pno,
                "caption": re.sub(r"\s+", " ", cap["block"]["text"])[:400],
                "bbox": [round(v, 1) for v in best] if best is not None else None,
                "width_fraction": round(best.width / page.rect.width, 2) if best is not None else None,
                "note": note or ("" if best is not None else "no graphics found next to the caption; use preview and --bbox"),
            }
            found.append(entry)
    # The same label can match twice (a caption and a sentence starting 'Figure 2.'): keep the one with a box.
    best_by_key: dict[tuple, dict] = {}
    for e in found:
        key = (e["kind"], e["number"].upper())
        cur = best_by_key.get(key)
        if cur is None or (cur["bbox"] is None and e["bbox"] is not None):
            best_by_key[key] = e
    return sorted(best_by_key.values(), key=lambda e: (e["page"], e["bbox"][1] if e["bbox"] else 0))


def table_text_region(cap, page, blocks, caps, body):
    pr, crect = page.rect, cap["rect"]
    col_width = max(crect.width, 0.38 * pr.width)
    below = sorted((b for b in blocks if b["rect"].y0 >= crect.y1 - 2 and b is not cap["block"]),
                   key=lambda b: b["rect"].y0)
    box = None
    for b in below:
        if is_paragraph(b, body, col_width) or CAPTION.match(b["text"]):
            break
        if h_overlap(b["rect"], crect) <= 0 and box is None:
            continue
        box = pymupdf.Rect(b["rect"]) if box is None else box | b["rect"]
    if box is None or box.height < 20:
        return None
    return pymupdf.Rect(box.x0 - PAD, box.y0 - PAD, box.x1 + PAD, box.y1 + PAD) & pr


# ------------------------------------------------------------------ commands

def pick(entries: list[dict], kind: str, number: str) -> dict:
    for e in entries:
        if e["kind"] == kind and e["number"].upper() == number.upper():
            return e
    have = ", ".join(f"{e['kind']} {e['number']}" for e in entries) or "none"
    sys.exit(f"{kind} {number} not found in this PDF (found: {have})")


def cmd_list(args) -> int:
    doc = pymupdf.open(args.pdf)
    entries = detect(doc, include_tables=args.tables)
    print(json.dumps({"pdf": args.pdf, "pages": doc.page_count, "items": entries}, indent=2, ensure_ascii=False))
    return 0


def cmd_preview(args) -> int:
    doc = pymupdf.open(args.pdf)
    if not 1 <= args.page <= doc.page_count:
        sys.exit(f"page {args.page} is out of range (1-{doc.page_count})")
    entries = [e for e in detect(doc, include_tables=True) if e["page"] == args.page and e["bbox"]]
    page = doc[args.page - 1]
    for e in entries:   # drawn on the in-memory page only; the PDF file is not changed
        r = pymupdf.Rect(e["bbox"])
        color = (0.85, 0.1, 0.1) if e["kind"] == "figure" else (0.1, 0.3, 0.85)
        page.draw_rect(r, color=color, width=1.2)
        page.insert_text((r.x0 + 2, r.y0 + 9), f"{e['kind']} {e['number']}", fontsize=8, color=color)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    page.get_pixmap(dpi=args.dpi).save(out)
    print(json.dumps({"out": str(out), "page": args.page,
                      "page_size_pt": [round(page.rect.width, 1), round(page.rect.height, 1)],
                      "boxes": [{"kind": e["kind"], "number": e["number"], "bbox": e["bbox"]} for e in entries]},
                     indent=2))
    return 0


def cmd_crop(args) -> int:
    doc = pymupdf.open(args.pdf)
    info: dict = {}
    if args.bbox:
        if not args.page:
            sys.exit("--bbox needs --page")
        try:
            x0, y0, x1, y1 = (float(v) for v in args.bbox.split(","))
        except ValueError:
            sys.exit("--bbox must be x0,y0,x1,y1 in PDF points")
        pno, box = args.page, pymupdf.Rect(x0, y0, x1, y1)
        info = {"source": "manual bbox"}
    else:
        if not (args.figure or args.table):
            sys.exit("give --figure N, --table N, or --page with --bbox")
        kind, number = ("figure", args.figure) if args.figure else ("table", args.table)
        e = pick(detect(doc, include_tables=True), kind, number)
        if e["bbox"] is None:
            sys.exit(f"{kind} {number} is on page {e['page']} but its box could not be detected; "
                     f"run preview on that page and pass --page {e['page']} --bbox x0,y0,x1,y1")
        pno, box = e["page"], pymupdf.Rect(e["bbox"])
        info = {"source": f"detected {kind} {number}", "caption": e["caption"], "note": e["note"]}
    if not 1 <= pno <= doc.page_count:
        sys.exit(f"page {pno} is out of range (1-{doc.page_count})")
    page = doc[pno - 1]
    box = box & page.rect
    if box.is_empty or box.width < 5 or box.height < 5:
        sys.exit("the box is empty or outside the page")

    dpi = args.dpi
    longest_in = max(box.width, box.height) / 72
    if longest_in * dpi > MAX_PIXELS:
        dpi = int(MAX_PIXELS / longest_in)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix = page.get_pixmap(clip=box, dpi=dpi, alpha=False)
    pix.save(out)
    result = {"out": str(out), "page": pno, "bbox": [round(v, 1) for v in box], "dpi": dpi,
              "pixels": [pix.width, pix.height], "aspect_ratio": round(box.width / box.height, 2), **info}
    if args.vector:
        vec = out.with_suffix(".pdf")
        new = pymupdf.open()
        target = new.new_page(width=box.width, height=box.height)
        target.show_pdf_page(target.rect, doc, pno - 1, clip=box)
        new.save(vec, garbage=4, deflate=True)
        result["vector"] = str(vec)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list the figures (and tables) with their boxes")
    p.add_argument("pdf")
    p.add_argument("--tables", action="store_true", help="include tables")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("preview", help="render a page with the detected boxes drawn on it")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--dpi", type=int, default=110)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("crop", help="crop a figure, a table, or a manual box")
    p.add_argument("pdf")
    p.add_argument("--figure", help="figure number, as printed in the caption")
    p.add_argument("--table", help="table number")
    p.add_argument("--page", type=int)
    p.add_argument("--bbox", help="x0,y0,x1,y1 in PDF points, top-left origin (overrides detection)")
    p.add_argument("--out", required=True)
    p.add_argument("--dpi", type=int, default=600)
    p.add_argument("--vector", action="store_true", help="also write a vector .pdf crop next to the PNG")
    p.set_defaults(func=cmd_crop)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
