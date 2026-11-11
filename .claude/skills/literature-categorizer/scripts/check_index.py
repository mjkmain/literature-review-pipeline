#!/usr/bin/env python3
"""Check index.md against papers.md and against its own conventions.

    python3 check_index.py reference/index.md [--papers reference/papers.md]

index.md must hold two tables:
    Category | Short name | Problem focus | Papers
    Paper | Year | Venue | Category | URL | arXiv | File

Prints a JSON report to stdout. Exit code: 0 = no errors, 1 = errors, 2 = unreadable.

    errors      must be fixed before the index is used
    warnings    judgment calls to look at (category sizes, naming)
    categories  the size of each category, for a quick look at the balance
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

EMPTY = {"", "-", "—", "–"}
SEPARATOR = re.compile(r"^:?-{2,}:?$")
LINK = re.compile(r"\[([^\]]*)\]\(\s*(\S+?)\s*\)")
SHORT_NAME = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
FILE = re.compile(r"^([a-z0-9_]+)/((?:19|20)\d\d)_([a-z0-9_]+)\.pdf$")
VAGUE = re.compile(r"^(other|others|misc|miscellaneous|general|various|uncategorized)\b", re.I)


def cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def tables(text: str) -> list[tuple[list[str], list[tuple[int, list[str]]]]]:
    """Every markdown table as (lowercased header, [(line number, cells)])."""
    out, header, rows = [], None, []
    for n, line in enumerate(text.splitlines() + [""], 1):
        if "|" not in line:
            if header is not None:
                out.append((header, rows))
            header, rows = None, []
            continue
        c = cells(line)
        if header is None:
            header = [x.lower() for x in c]
        elif not all(SEPARATOR.match(x) or not x for x in c):
            rows.append((n, c))
    return out


def find(tabs, *needed):
    for header, rows in tabs:
        if all(k in header for k in needed):
            return header, rows
    return None, []


def plain(cell: str) -> str:
    """Cell text without markdown link syntax, bold markers or backticks."""
    m = LINK.search(cell)
    return re.sub(r"[*`]", "", m.group(1) if m else cell).strip()


def norm(title: str) -> str:
    t = unicodedata.normalize("NFKD", title).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("index")
    ap.add_argument("--papers", help="papers.md to compare with (default: papers.md next to the index)")
    args = ap.parse_args()
    papers_path = args.papers or os.path.join(os.path.dirname(os.path.abspath(args.index)), "papers.md")

    try:
        tabs = tables(open(args.index, encoding="utf-8").read())
    except OSError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    ch, crows = find(tabs, "category", "short name", "problem focus")
    ph, prows = find(tabs, "paper", "category", "file")
    if ch is None or ph is None or not crows or not prows:
        print(json.dumps({"error": "index.md needs a category table (Category | Short name | Problem focus | Papers) "
                                   "and a paper table (Paper | Year | Venue | Category | URL | arXiv | File)"}))
        return 2

    errors, warnings = [], []
    err = lambda line, msg: errors.append({"line": line, "issue": msg})
    warn = lambda line, msg: warnings.append({"line": line, "issue": msg})
    col = lambda header, row, name: row[header.index(name)] if name in header and header.index(name) < len(row) else ""

    for name in ("year", "venue", "url", "arxiv"):
        if name not in ph:
            err(None, f"paper table has no {name!r} column")

    # ---- category table
    cats: dict[str, dict] = {}
    shorts: dict[str, str] = {}
    for n, row in crows:
        name, short = plain(col(ch, row, "category")), plain(col(ch, row, "short name"))
        focus, count = col(ch, row, "problem focus"), col(ch, row, "papers")
        if not name:
            err(n, "category row without a name")
            continue
        if name in cats:
            err(n, f"category {name!r} is listed twice")
        cats[name] = {"short": short, "declared": count, "papers": 0}
        if not SHORT_NAME.match(short):
            err(n, f"short name {short!r} must be lowercase words joined by underscores (it becomes a folder name)")
        elif short in shorts:
            err(n, f"short name {short!r} is used by both {shorts[short]!r} and {name!r}")
        shorts.setdefault(short, name)
        if len(short) > 30:
            warn(n, f"short name {short!r} is long for a folder name; 1-3 words is enough")
        if len(focus.split()) < 8:
            err(n, f"problem focus of {name!r} is missing or too short to define the category")
        if VAGUE.match(name):
            warn(n, f"category {name!r} is a leftover bin, not a problem; place its papers in real categories")

    # ---- paper table
    seen_titles: dict[str, int] = {}
    seen_files: dict[str, int] = {}
    for n, row in prows:
        title, cat = plain(col(ph, row, "paper")), plain(col(ph, row, "category"))
        file_ = plain(col(ph, row, "file"))
        if not title:
            err(n, "paper row without a title")
            continue
        key = norm(title)
        if key in seen_titles:
            err(n, f"{title!r} appears twice (also line {seen_titles[key]}); each paper gets exactly one category")
        seen_titles.setdefault(key, n)
        if cat not in cats:
            err(n, f"{title!r}: category {cat!r} is not in the category table (names must match exactly)")
        else:
            cats[cat]["papers"] += 1
        if not re.fullmatch(r"(19|20)\d\d", col(ph, row, "year")):
            err(n, f"{title!r}: Year is not a 4-digit year")
        url, arxiv = col(ph, row, "url"), col(ph, row, "arxiv")
        if url in EMPTY and arxiv in EMPTY:
            err(n, f"{title!r}: neither URL nor arXiv is filled; the download step has nothing to fetch")
        m = FILE.match(file_)
        if not m:
            err(n, f"{title!r}: File {file_!r} does not follow <category_short>/<year>_<short_name>_<venue>.pdf (lowercase, underscores)")
        else:
            if cat in cats and m.group(1) != cats[cat]["short"]:
                err(n, f"{title!r}: File is in folder {m.group(1)!r} but its category's short name is {cats[cat]['short']!r}")
            if m.group(2) != col(ph, row, "year"):
                err(n, f"{title!r}: year in File ({m.group(2)}) differs from the Year column")
            if "_" not in m.group(3):
                err(n, f"{title!r}: File needs both a short name and a venue after the year")
        if file_ in seen_files:
            err(n, f"{title!r}: File {file_!r} is also used on line {seen_files[file_]}")
        seen_files.setdefault(file_, n)

    # ---- category sizes
    total = len(seen_titles)
    for name, c in cats.items():
        if c["papers"] == 0:
            err(None, f"category {name!r} has no papers")
        if c["declared"].isdigit() and int(c["declared"]) != c["papers"]:
            err(None, f"category {name!r} says {c['declared']} papers but the paper table has {c['papers']}")
        if c["papers"] == 1:
            warn(None, f"category {name!r} has a single paper; merge it unless its problem is truly separate")
        if total >= 12 and c["papers"] > 0.4 * total:
            warn(None, f"category {name!r} holds {c['papers']} of {total} papers; it probably hides more than one problem")
    if total >= 12 and not 4 <= len(cats) <= 9:
        warn(None, f"{len(cats)} categories for {total} papers; 4-9 usually gives a readable landscape")

    # ---- against papers.md
    compared = False
    if os.path.exists(papers_path):
        h, rows = find(tables(open(papers_path, encoding="utf-8").read()), "paper", "problem")
        if h is not None:
            compared = True
            source = {norm(plain(col(h, r, "paper"))): plain(col(h, r, "paper")) for _, r in rows}
            for key, title in source.items():
                if key and key not in seen_titles:
                    err(None, f"missing from index: {title!r} (every collected paper is categorized)")
            for key, n in seen_titles.items():
                if key not in source:
                    err(n, "paper is in the index but not in papers.md; titles must be copied unchanged")
    else:
        warn(None, f"{papers_path} not found; could not check that every collected paper is in the index")

    print(json.dumps({
        "index": args.index,
        "papers": total,
        "compared_with_papers_md": compared,
        "categories": {name: c["papers"] for name, c in cats.items()},
        "errors": errors,
        "warnings": warnings,
    }, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
