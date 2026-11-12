#!/usr/bin/env python3
"""Scan whole proceedings by title: every paper of every venue in a year range.

    scan_proceedings.py --years 2023-2026 \
        --thread "edit propagation=cross-?lingual.*(edit|unlearn)|multilingual.*(edit|unlearn)" \
        --thread "evaluation=(edit|unlearn).*(benchmark|evaluat)" \
        [--venues acl,iclr,icml,neurips] [--max-per-thread 150] [--refresh]

Web search finds what is well linked; this finds what is merely published. It
downloads the full title lists and matches each `--thread "name=regex"`
(case-insensitive, on the title only):

  acl      the ACL Anthology dump: ACL, EMNLP, NAACL, EACL, AACL, COLING, TACL,
           CL, Findings and workshops (one file, all years)
  iclr     iclr.cc/virtual/<year>/papers.html
  icml     icml.cc/virtual/<year>/papers.html
  neurips  neurips.cc/virtual/<year>/papers.html

Prints JSON: per thread, the matching papers with title, venue, year and URL.
A match is a candidate, not a selection: the title says little, so open the
page before a paper goes into the list. arXiv-only papers are not covered.

Lists are cached for 7 days in ~/.cache/literature-review (--refresh to renew).
Standard library only.
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache" / "literature-review"
TTL = 7 * 24 * 3600
UA = "Mozilla/5.0 (literature-review scan_proceedings)"
ANTHOLOGY = "https://aclanthology.org/anthology.bib.gz"
VIRTUAL = {"iclr": "ICLR", "icml": "ICML", "neurips": "NeurIPS"}
# Anthology ids look like 2024.acl-long.627, 2025.findings-emnlp.12, 2024.repl4nlp-1.3.
ACL_MAIN = {"acl": "ACL", "emnlp": "EMNLP", "naacl": "NAACL", "eacl": "EACL", "aacl": "AACL",
            "ijcnlp": "IJCNLP-AACL", "coling": "COLING", "lrec": "LREC", "tacl": "TACL", "cl": "CL"}
MAIN_TRACKS = {"long", "short", "main", "1", "2", ""}   # anything else (srw, demo, tutorials, industry) is labelled


def fetch(url: str, name: str, refresh: bool) -> bytes | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    if path.is_file() and not refresh and time.time() - path.stat().st_mtime < TTL:
        return path.read_bytes()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"warning: could not fetch {url}: {e}", file=sys.stderr)
        return path.read_bytes() if path.is_file() else None
    path.write_bytes(data)
    return data


def clean(title: str) -> str:
    title = html.unescape(re.sub(r"<[^>]+>", "", title))
    title = re.sub(r"\\[a-zA-Z]+\s*|[{}]", "", title)      # bib braces and simple commands
    return re.sub(r"\s+", " ", title).strip()


def acl_venue(url: str, booktitle: str) -> str:
    """Venue label from the Anthology id; workshops fall back to their proceedings title."""
    booktitle = clean(booktitle)
    m = re.search(r"/(?:19|20)\d\d\.([a-z0-9]+)-([a-z0-9]+)\.", url + ".")
    if m:
        event, track = m.group(1), m.group(2)
        if event == "findings":
            return "Findings of " + ACL_MAIN.get(track, track.upper())
        if event in ACL_MAIN:
            return ACL_MAIN[event] if track in MAIN_TRACKS or track.isdigit() else f"{ACL_MAIN[event]} ({track})"
        return f"Workshop ({event}): {booktitle[:60]}"
    return booktitle[:80]


def anthology(years: range, refresh: bool) -> list[dict]:
    raw = fetch(ANTHOLOGY, "anthology.bib.gz", refresh)
    if raw is None:
        return []
    text = gzip.decompress(raw).decode("utf-8", errors="replace")
    field = lambda entry, name: (re.search(rf'^\s*{name}\s*=\s*"(.*?)",?\s*$', entry, re.M | re.S) or [None, ""])[1]
    out = []
    for entry in re.split(r"\n(?=@)", text):
        if not entry.startswith(("@inproceedings", "@article")):
            continue
        y = re.search(r'^\s*year\s*=\s*"(\d{4})"', entry, re.M)
        if not y or int(y.group(1)) not in years:
            continue
        title, url = clean(field(entry, "title")), field(entry, "url")
        venue = acl_venue(url, field(entry, "booktitle") or field(entry, "journal"))
        if title and url:
            out.append({"title": title, "venue": venue, "year": int(y.group(1)), "url": url})
    return out


def virtual(site: str, years: range, refresh: bool) -> list[dict]:
    out = []
    for year in years:
        raw = fetch(f"https://{site}.cc/virtual/{year}/papers.html", f"{site}-{year}.html", refresh)
        if raw is None:
            continue
        page = raw.decode("utf-8", errors="replace")
        seen = set()
        for path, title in re.findall(rf'<a href="(/virtual/{year}/(?:poster|oral|spotlight)/\d+)">(.*?)</a>', page, re.S):
            title = clean(title)
            if title and title.lower() not in seen:
                seen.add(title.lower())
                out.append({"title": title, "venue": VIRTUAL[site], "year": year, "url": f"https://{site}.cc{path}"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", required=True, help="e.g. 2023-2026 or 2023- (open end = this year)")
    ap.add_argument("--thread", action="append", required=True, metavar="NAME=REGEX",
                    help="repeatable; regex is matched case-insensitively against titles")
    ap.add_argument("--venues", default="acl,iclr,icml,neurips")
    ap.add_argument("--max-per-thread", type=int, default=150)
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    args = ap.parse_args()

    m = re.fullmatch(r"\s*(\d{4})\s*-\s*(\d{4})?\s*", args.years)
    if not m:
        ap.error("--years must look like 2023-2026 or 2023-")
    years = range(int(m.group(1)), int(m.group(2) or time.localtime().tm_year) + 1)

    threads = []
    for spec in args.thread:
        name, sep, pattern = spec.partition("=")
        if not sep or not pattern.strip():
            ap.error(f"--thread needs NAME=REGEX, got: {spec}")
        try:
            threads.append((name.strip(), re.compile(pattern.strip(), re.I)))
        except re.error as e:
            ap.error(f"bad regex for thread '{name}': {e}")

    papers, scanned = [], {}
    for venue in [v.strip().lower() for v in args.venues.split(",") if v.strip()]:
        if venue == "acl":
            found = anthology(years, args.refresh)
        elif venue in VIRTUAL:
            found = virtual(venue, years, args.refresh)
        else:
            ap.error(f"unknown venue '{venue}' (choose from acl, iclr, icml, neurips)")
        scanned[venue] = len(found)
        papers += found

    result = {"years": f"{years.start}-{years.stop - 1}", "titles_scanned": scanned, "threads": {}}
    for name, rx in threads:
        hits = [p for p in papers if rx.search(p["title"])]
        hits.sort(key=lambda p: (p["year"], p["venue"], p["title"]))
        entry = {"matches": len(hits), "papers": hits[:args.max_per_thread]}
        if len(hits) > args.max_per_thread:
            entry["note"] = (f"{len(hits)} titles match; showing {args.max_per_thread}. "
                             "The regex is too broad for this thread: narrow it.")
        result["threads"][name] = entry
    if not any(scanned.values()):
        result["error"] = "no proceedings could be downloaded"
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if any(scanned.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
