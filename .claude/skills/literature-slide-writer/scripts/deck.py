#!/usr/bin/env python3
"""Bookkeeping for a literature-review slide deck: everything that is not writing.

    deck.py prepare  <index.md> --template <template dir> --deck <deck dir>
    deck.py assemble <deck dir> [--lang ko]
    deck.py check    <deck dir> [--lang ko] [--no-build]
    deck.py sheets   <deck dir> --out <new dir> [--lang ko]

prepare   copy the template to the deck directory (only if it does not exist yet),
          read index.md / papers.md, and write <deck>/papers.json: one entry per paper
          with the paths its slide, figure and notes must be written to, and whether
          they exist already. Run it again at any time to see what is still to do.
assemble  write sections/overview.tex and sections/paper_summaries.tex from
          papers.json and the per-paper notes. With --lang ko, write only
          sections-ko/paper_summaries.tex (the Korean overview is translated by hand).
check     static checks on every paper slide, then build the PDF with `make` and
          look for slides whose content runs off the page.
sheets    render the built PDF as contact sheets (PNG) for a visual pass.

All commands print JSON. `check` exits 1 when it reports errors.
Run with the project's .venv/bin/python (PyMuPDF and Pillow are needed for check/sheets).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PER_CATEGORY_SLIDE = 7     # paper rows that fit on one category overview slide
LIMITS = {"en": {"title": 50, "bullet": 90, "total": 380},   # characters; measured against the template
          "ko": {"title": 32, "bullet": 55, "total": 230}}
MIN_FIGURE_PX = 1200       # longest side; a 600-DPI crop of any real figure is far above this
SEPARATOR = re.compile(r"^:?-{2,}:?$")
LINK = re.compile(r"\[([^\]]*)\]\(\s*(\S+?)\s*\)")


# ------------------------------------------------------------------ small helpers

def fail(msg: str, code: int = 2):
    print(json.dumps({"error": msg}, ensure_ascii=False))
    sys.exit(code)


def tex_escape(text: str) -> str:
    """Plain text -> LaTeX text."""
    out = []
    for ch in text:
        out.append({
            "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
            "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        }.get(ch, ch))
    return "".join(out)


def cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def tables(text: str):
    out, header, rows = [], None, []
    for line in text.splitlines() + [""]:
        if "|" not in line:
            if header is not None:
                out.append((header, rows))
            header, rows = None, []
            continue
        c = cells(line)
        if header is None:
            header = [x.lower() for x in c]
        elif not all(SEPARATOR.match(x) or not x for x in c):
            rows.append(c)
    return out


def find_table(tabs, *needed):
    for header, rows in tabs:
        if all(k in header for k in needed):
            return header, rows
    return None, []


def plain(cell: str) -> str:
    m = LINK.search(cell)
    return re.sub(r"[*`]", "", m.group(1) if m else cell).strip()


def url_of(cell: str) -> str:
    m = LINK.search(cell)
    if m and m.group(2).startswith("http"):
        return m.group(2)
    m = re.search(r"https?://[^\s|)>]+", cell)
    return m.group(0) if m else ""


def norm(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


def load_manifest(deck: Path) -> dict:
    path = deck / "papers.json"
    if not path.is_file():
        fail(f"{path} not found; run `deck.py prepare` first")
    return json.loads(path.read_text(encoding="utf-8"))


def sections_dir(lang: str) -> str:
    return "sections-ko" if lang == "ko" else "sections"


def first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return (m.group(1) if m else text.strip())


# ------------------------------------------------------------------ prepare

def cmd_prepare(args) -> int:
    index = Path(args.index)
    if not index.is_file():
        fail(f"index not found: {index}")
    ref = index.parent
    tabs = tables(index.read_text(encoding="utf-8"))
    ch, crows = find_table(tabs, "category", "short name", "problem focus")
    ph, prows = find_table(tabs, "paper", "category", "file")
    if ch is None or ph is None:
        fail("index.md needs a category table and a paper table (see the categorize step)")
    col = lambda h, r, n: r[h.index(n)] if n in h and h.index(n) < len(r) else ""

    problems: dict[str, str] = {}
    papers_md = ref / "papers.md"
    if papers_md.is_file():
        h, rows = find_table(tables(papers_md.read_text(encoding="utf-8")), "paper", "problem")
        if h is not None:
            problems = {norm(plain(col(h, r, "paper"))): col(h, r, "problem") for r in rows}

    m = re.search(r"^#\s*Index:\s*(.+)$", index.read_text(encoding="utf-8"), re.M)
    area = m.group(1).strip() if m else ""

    deck = Path(args.deck)
    copied = False
    if not deck.exists():
        template = Path(args.template)
        if not (template / "main.tex").is_file():
            fail(f"template not found: {template} (expected main.tex inside)")
        shutil.copytree(template, deck, ignore=shutil.ignore_patterns("build", "*.pdf", ".DS_Store"))
        copied = True
    elif not (deck / "main.tex").is_file():
        fail(f"{deck} exists but is not a slide deck (no main.tex); choose another --deck")

    categories = [{"name": plain(col(ch, r, "category")), "short": plain(col(ch, r, "short name")),
                   "focus": col(ch, r, "problem focus")} for r in crows if plain(col(ch, r, "category"))]
    short_of = {c["name"]: c["short"] for c in categories}

    papers = []
    for r in prows:
        title, cat, file_ = plain(col(ph, r, "paper")), plain(col(ph, r, "category")), plain(col(ph, r, "file"))
        if not title or not file_:
            continue
        key = Path(file_).stem
        short = short_of.get(cat) or Path(file_).parent.name
        arxiv = url_of(col(ph, r, "arxiv"))
        aid = re.search(r"(\d{4}\.\d{4,5})", arxiv)
        papers.append({
            "key": key, "title": title, "year": col(ph, r, "year"), "venue": col(ph, r, "venue"),
            "category": cat, "category_short": short,
            "url": url_of(col(ph, r, "url")), "arxiv": arxiv, "arxiv_id": aid.group(1) if aid else "",
            "problem": problems.get(norm(title), ""),
            "pdf": str((ref / file_).resolve()),
            "tex": f"sections/papers/{short}/{key}.tex",
            "image": f"images/{short}/{key}.png",
            "notes": f"notes/{key}.json",
        })

    for p in papers:
        p["pdf_exists"] = Path(p["pdf"]).is_file()
        p["done"] = all((deck / p[k]).is_file() for k in ("tex", "image", "notes"))
    for sub in {p["category_short"] for p in papers}:
        for base in ("sections/papers", "sections-ko/papers", "images"):
            (deck / base / sub).mkdir(parents=True, exist_ok=True)
    (deck / "notes").mkdir(exist_ok=True)

    manifest = {"area": area, "index": str(index.resolve()), "deck": str(deck.resolve()),
                "categories": categories, "papers": papers}
    (deck / "papers.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    todo = [p["key"] for p in papers if p["pdf_exists"] and not p["done"]]
    print(json.dumps({
        "deck": str(deck), "template_copied": copied, "area": area,
        "categories": len(categories), "papers": len(papers),
        "done": sum(p["done"] for p in papers),
        "todo": todo,
        "missing_pdf": [{"key": p["key"], "title": p["title"]} for p in papers if not p["pdf_exists"]],
        "manifest": str(deck / "papers.json"),
    }, indent=2, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ assemble

def load_notes(deck: Path, paper: dict) -> dict:
    path = deck / paper["notes"]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cmd_assemble(args) -> int:
    deck = Path(args.deck)
    man = load_manifest(deck)
    sec = sections_dir(args.lang)
    by_cat: dict[str, list[dict]] = {c["name"]: [] for c in man["categories"]}
    skipped = []
    for p in man["papers"]:
        if (deck / sec / Path(p["tex"]).relative_to("sections")).is_file():
            by_cat.setdefault(p["category"], []).append(p)
        else:
            skipped.append(p["key"])

    # ---- Section 2: one subsection per category, one \input per paper
    lines = ["% Generated by deck.py assemble -- do not edit; edit the files under papers/ instead.",
             r"\section{Paper Summaries}"]
    for c in man["categories"]:
        if not by_cat[c["name"]]:
            continue
        lines.append("")
        lines.append(rf"\subsection{{{tex_escape(c['name'])}}}")
        for p in by_cat[c["name"]]:
            lines.append(rf"\input{{\slidedir/papers/{p['category_short']}/{p['key']}}}")
    (deck / sec / "paper_summaries.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    written = [f"{sec}/paper_summaries.tex"]

    # ---- Section 1 (English only; the Korean overview is a translation of this file)
    if args.lang != "ko":
        o = ["% Generated by deck.py assemble from index.md and notes/*.json.",
             "% Edit index.md or the notes and run assemble again, rather than editing this file.",
             r"\section{Overview}", "", r"\begin{frame}{Research Landscape}", r"  \begin{categorytable}"]
        try:   # optional one-line texts for the landscape slide, keyed by category short name
            landscape = json.loads((deck / "notes" / "_landscape.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            landscape = {}
        for c in man["categories"]:
            n = len(by_cat[c["name"]])
            if n:
                line = landscape.get(c["short"]) or first_sentence(c["focus"])
                o.append(rf"    \categoryrow{{{tex_escape(c['name'])}}}{{{tex_escape(line)}}}{{{n}}}")
        o += [r"  \end{categorytable}", r"\end{frame}"]
        for c in man["categories"]:
            papers = by_cat[c["name"]]
            if not papers:
                continue
            chunks = [papers[i:i + PER_CATEGORY_SLIDE] for i in range(0, len(papers), PER_CATEGORY_SLIDE)]
            for i, chunk in enumerate(chunks, 1):
                suffix = f" ({i}/{len(chunks)})" if len(chunks) > 1 else ""
                o += ["", rf"\begin{{frame}}{{{tex_escape(c['name'])}{suffix}}}",
                      rf"  \categoryfocus{{{tex_escape(c['focus'])}}}", r"  \begin{paperlist}"]
                for p in chunk:
                    notes = load_notes(deck, p)
                    name = notes.get("short_title") or p["title"][:40]
                    focus = notes.get("focus") or first_sentence(p["problem"]) or ""
                    o.append(rf"    \paperrow{{{tex_escape(name)}}}{{{tex_escape(p['venue'])} {p['year']}}}{{{tex_escape(focus)}}}")
                o += [r"  \end{paperlist}", r"\end{frame}"]
        (deck / sec / "overview.tex").write_text("\n".join(o) + "\n", encoding="utf-8")
        written.append(f"{sec}/overview.tex")

    print(json.dumps({"written": written, "papers_included": sum(len(v) for v in by_cat.values()),
                      "papers_without_slide": skipped}, indent=2, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------ check

def strip_comments(tex: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*", "", ln) for ln in tex.splitlines())


def strip_math(tex: str) -> str:
    tex = re.sub(r"\$\$.*?\$\$", " ", tex, flags=re.S)
    tex = re.sub(r"(?<!\\)\$.*?(?<!\\)\$", " ", tex, flags=re.S)
    return re.sub(r"\\\(.*?\\\)", " ", tex, flags=re.S)


def check_frame(deck: Path, p: dict, lang: str) -> list[str]:
    sec = sections_dir(lang)
    path = deck / sec / Path(p["tex"]).relative_to("sections")
    if not path.is_file():
        return [f"slide file missing: {path.relative_to(deck)}"]
    raw = path.read_text(encoding="utf-8")
    tex = strip_comments(raw)
    issues = []
    if tex.count(r"\begin{frame}") != 1 or tex.count(r"\end{frame}") != 1:
        issues.append("must contain exactly one frame")
    if p["image"] not in tex:
        issues.append(f"does not include its figure {p['image']}")
    for ln in raw.splitlines():
        if not ln.lstrip().startswith("%") and re.search(r"(?<!\\)%", ln):
            issues.append("a bare % inside a line: write \\% (a bare % comments out the rest of the line)")
            break
    body = strip_math(tex)
    body_no_paths = re.sub(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}", "", body)
    if re.search(r"(?<!\\)&", body_no_paths):
        issues.append("unescaped & (write \\&)")
    if re.search(r"(?<!\\)#", body_no_paths):
        issues.append("unescaped # (write \\#)")
    if re.search(r"(?<!\\)_", body_no_paths):
        issues.append("unescaped _ outside math (write \\_)")
    def visible(t: str) -> str:
        t = re.sub(r"\\setlength\{[^}]*\}\{[^}]*\}", "", t)
        t = re.sub(r"\$[^$]*\$", "xxxx", t)                 # inline math: count as a short word
        return re.sub(r"\s+", " ", re.sub(r"\\[a-zA-Z]+\*?|[{}]", "", t)).strip()

    limit = LIMITS["ko" if lang == "ko" else "en"]
    m = re.search(r"\\begin\{frame\}(?:\[[^\]]*\])?\{(.*)\}\s*$", tex, re.M)
    if m and len(visible(m.group(1))) > limit["title"]:
        issues.append(f"frame title is {len(visible(m.group(1)))} characters (limit {limit['title']}); it is cut off at the right edge")
    total = 0
    for name, allowed in (("Problem", (2, 2)), ("Method", (2, 3))):
        m = re.search(r"\\begin\{block\}\{%s\}(.*?)\\end\{block\}" % name, tex, re.S)
        if not m:
            issues.append(f"no {name} block (block titles stay in English)")
            continue
        items = [i for i in re.split(r"\\item\b", m.group(1))[1:]]
        items = [visible(re.sub(r"\\end\{itemize\}.*", "", i, flags=re.S)) for i in items]
        if not allowed[0] <= len(items) <= allowed[1]:
            want = "2" if allowed == (2, 2) else "2 or 3"
            issues.append(f"{name} has {len(items)} bullets; use {want}")
        for it in items:
            total += len(it)
            if len(it) > limit["bullet"]:
                issues.append(f"{name} bullet is {len(it)} characters (limit {limit['bullet']}): '{it[:45]}...'")
    if total > limit["total"]:
        issues.append(f"bullets total {total} characters (limit {limit['total']}); the slide will overflow")
    layout = ["\\papermeta{", "\\figcaption{", "\\paperbody", "{0.42\\textwidth}", "{0.55\\textwidth}"]
    if any(piece not in tex for piece in layout):
        issues.append("frame does not follow the layout in references/paper-agent.md (spacing/column commands changed)")
    if "Paper Title:" in tex or "Main figure" in tex or "Author et al." in tex:
        issues.append("template placeholder text is still in the slide")
    if lang != "ko":
        image = deck / p["image"]
        if not image.is_file():
            issues.append(f"figure missing: {p['image']}")
        else:
            try:
                from PIL import Image
                with Image.open(image) as im:
                    if max(im.size) < MIN_FIGURE_PX:
                        issues.append(f"figure is only {im.size[0]}x{im.size[1]} px; crop it again at 600 DPI")
            except ImportError:
                pass
        notes = load_notes(deck, p)
        for field in ("short_title", "focus"):
            if not notes.get(field):
                issues.append(f"notes/{p['key']}.json has no '{field}'")
    return issues


def tex_env() -> dict:
    env = dict(os.environ)
    extra = sorted(glob.glob(os.path.expanduser("~/.TinyTeX/bin/*/")))
    if extra:
        env["PATH"] = extra[0] + os.pathsep + env.get("PATH", "")
    return env


def build(deck: Path, lang: str) -> dict:
    env = tex_env()
    if not shutil.which("latexmk", path=env["PATH"]) or not shutil.which("xelatex", path=env["PATH"]):
        return {"built": False, "reason": "xelatex/latexmk not found; run ./setup.sh in the project root"}
    target = "ko" if lang == "ko" else "en"
    proc = subprocess.run(["make", target], cwd=deck, env=env, capture_output=True, text=True, errors="replace")
    pdf = deck / f"slides-{target}.pdf"
    log = deck / "build" / f"slides-{target}.log"
    errors = []
    if log.is_file():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("!"):
                where = next((l for l in lines[i:i + 8] if re.match(r"l\.\d+", l)), "")
                errors.append(f"{ln} {where}".strip())
    if proc.returncode != 0 and not errors:
        errors.append((proc.stdout + proc.stderr)[-600:])
    return {"built": proc.returncode == 0 and pdf.is_file(), "pdf": str(pdf), "latex_errors": errors[:10]}


def overflowing_pages(pdf: Path) -> list[dict]:
    """Slides whose content runs below the page or into the footer."""
    import pymupdf
    out = []
    doc = pymupdf.open(pdf)
    for i, page in enumerate(doc, 1):
        h = page.rect.height
        far = pymupdf.Rect(-2000, -2000, 4000, 4000)     # also see what was pushed off the page
        blocks = page.get_text("dict", clip=far)["blocks"]
        lowest, culprit = 0.0, ""
        for b in blocks:
            y1 = b["bbox"][3]
            text = ""
            if b.get("type") != 0:
                continue                                   # images are handled below
            if b.get("type") == 0:
                text = " ".join(s["text"] for ln in b["lines"] for s in ln["spans"]).strip()
                if not text or (y1 > h - 16 and len(text) <= 4):   # the page mark in the footer
                    continue
            if y1 > lowest:
                lowest, culprit = y1, text[:60] or "(figure)"
        for im in page.get_image_info():
            if im["bbox"][3] > h + 2 and im["bbox"][3] > lowest:   # an image pushed below the page
                lowest, culprit = im["bbox"][3], "(figure)"
        widest = max([b["bbox"][2] for b in blocks if b.get("type") == 0] + [0])
        if widest > page.rect.width + 1:
            first = page.get_text().strip().splitlines()
            out.append({"page": i, "slide": (first[0] if first else "")[:70],
                        "overflow_pt": round(widest - page.rect.width, 1), "lowest_content": "text runs past the right edge (title too long?)"})
        if lowest > h - 5:
            first = page.get_text().strip().splitlines()
            title = next((t for t in first if len(t.strip()) > 3), "") if first else ""
            out.append({"page": i, "slide": title.strip()[:70], "overflow_pt": round(lowest - (h - 5), 1),
                        "lowest_content": culprit})
    return out


def cmd_check(args) -> int:
    deck = Path(args.deck)
    man = load_manifest(deck)
    errors, per_paper = [], {}
    for p in man["papers"]:
        issues = check_frame(deck, p, args.lang)
        if issues:
            per_paper[p["key"]] = issues
    sec = sections_dir(args.lang)
    for name in ("overview.tex", "paper_summaries.tex", "open_problems.tex", "title.tex"):
        path = deck / sec / name
        if not path.is_file():
            errors.append(f"{sec}/{name} is missing")
        elif re.search(r"Category A|Paper1 Short Title|Literature Review: Topic|\\item A\b", path.read_text(encoding="utf-8")):
            errors.append(f"{sec}/{name} still holds the template's placeholder content")
    op = deck / sec / "open_problems.tex"
    if op.is_file():
        frames = re.findall(r"\\begin\{frame\}.*?\\end\{frame\}", strip_comments(op.read_text(encoding="utf-8")), re.S)
        if not 4 <= len(frames) <= 6 and "\\item A" not in op.read_text(encoding="utf-8"):
            errors.append(f"{sec}/open_problems.tex has {len(frames)} open problems; write 4-6, one frame each")
        cap = 60 if args.lang == "ko" else 100
        for n, fr in enumerate(frames, 1):
            items = [re.sub(r"\s+", " ", re.sub(r"\\[a-zA-Z]+\*?(\{[^}]*\}\{[^}]*\})?|[{}]", "", i)).strip()
                     for i in (re.sub(r"\\end\{itemize\}.*", "", j, flags=re.S) for j in re.split(r"\\item\b", fr)[1:])]
            if len(items) > 7:
                errors.append(f"{sec}/open_problems.tex frame {n}: {len(items)} bullets; at most 7 fit (2 + 2 + up to 3)")
            long = [i for i in items if len(i) > cap]
            if long:
                errors.append(f"{sec}/open_problems.tex frame {n}: {len(long)} bullet(s) over {cap} characters, "
                              f"e.g. '{long[0][:45]}...' (each bullet must fit on one line)")
    result = {"deck": str(deck), "lang": args.lang, "papers": len(man["papers"]),
              "slide_issues": per_paper, "errors": errors}
    if not args.no_build:
        b = build(deck, args.lang)
        result["build"] = b
        if b.get("built"):
            try:
                result["overflowing_slides"] = overflowing_pages(Path(b["pdf"]))
            except ImportError:
                result["overflowing_slides"] = "PyMuPDF not available; run with .venv/bin/python"
    bad = bool(per_paper or errors
               or (not args.no_build and (not result["build"].get("built") or result.get("overflowing_slides"))))
    result["ok"] = not bad
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if bad else 0


# ------------------------------------------------------------------ sheets

def cmd_sheets(args) -> int:
    import pymupdf
    from PIL import Image, ImageDraw
    deck = Path(args.deck)
    pdf = deck / f"slides-{'ko' if args.lang == 'ko' else 'en'}.pdf"
    if not pdf.is_file():
        fail(f"{pdf} not found; run `deck.py check` to build it")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    cols, rows, gap = 3, 3, 8
    sheets = []
    for start in range(0, doc.page_count, cols * rows):
        thumbs = []
        for i in range(start, min(start + cols * rows, doc.page_count)):
            pix = doc[i].get_pixmap(dpi=args.dpi, alpha=False)
            thumbs.append((i + 1, Image.frombytes("RGB", (pix.width, pix.height), pix.samples)))
        w, h = thumbs[0][1].size
        sheet = Image.new("RGB", (cols * (w + gap) + gap, rows * (h + gap + 12) + gap), (70, 70, 70))
        draw = ImageDraw.Draw(sheet)
        for n, (page_no, im) in enumerate(thumbs):
            x, y = gap + (n % cols) * (w + gap), gap + (n // cols) * (h + gap + 12)
            draw.text((x, y), f"p{page_no}", fill=(255, 255, 255))
            sheet.paste(im, (x, y + 12))
        path = out / f"sheet-{len(sheets) + 1:02d}.png"
        sheet.save(path)
        sheets.append(str(path))
    print(json.dumps({"pdf": str(pdf), "pages": doc.page_count, "sheets": sheets}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("index")
    p.add_argument("--template", required=True)
    p.add_argument("--deck", required=True)
    p.set_defaults(func=cmd_prepare)
    p = sub.add_parser("assemble")
    p.add_argument("deck")
    p.add_argument("--lang", choices=["en", "ko"], default="en")
    p.set_defaults(func=cmd_assemble)
    p = sub.add_parser("check")
    p.add_argument("deck")
    p.add_argument("--lang", choices=["en", "ko"], default="en")
    p.add_argument("--no-build", action="store_true")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("sheets")
    p.add_argument("deck")
    p.add_argument("--out", required=True)
    p.add_argument("--lang", choices=["en", "ko"], default="en")
    p.add_argument("--dpi", type=int, default=75)
    p.set_defaults(func=cmd_sheets)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
