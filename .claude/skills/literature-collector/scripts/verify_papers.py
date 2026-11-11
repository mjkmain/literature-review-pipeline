#!/usr/bin/env python3
"""Check a papers.md table against the live web.

Reads the table (columns: Paper | Year | Venue | URL | arXiv | Problem), opens
every link, and reports rows whose link is dead, points at a different paper, or
breaks the table's conventions. Standard library only.

    python3 verify_papers.py reference/papers.md [--min 30] [--workers 8] [--offline]

Progress goes to stderr, a JSON report to stdout.
Exit code: 0 = no errors, 1 = at least one error, 2 = the table could not be read.

Report fields
    errors      must be fixed: the row is wrong or incomplete
    warnings    look at each one; fix it or decide it is fine
    unverified  the site did not answer (blocked or timed out); check these by hand
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import difflib
import html
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
REQUIRED = ["paper", "year", "venue", "url", "arxiv", "problem"]
EMPTY = {"", "-", "—", "–", "n/a", "na", "none"}
ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
# Titles that announce a survey-type paper. "review"/"overview" alone are too
# common in ordinary titles, so they only count in survey-like phrasings.
SURVEY = re.compile(
    r"\b(survey|surveys|tutorial|position paper|systematization of knowledge|sok"
    r"|(?:a|an|systematic|literature|comprehensive|critical|brief|scoping)\s+(?:review|overview))\b",
    re.I,
)
BOT_WALL = re.compile(r"verifying your browser|just a moment|attention required|are you a robot|access denied|captcha", re.I)
SEPARATOR = re.compile(r"^:?-{2,}:?$")
LINK = re.compile(r"\[([^\]]*)\]\(\s*(\S+?)\s*\)")
BARE_URL = re.compile(r"https?://[^\s|)>]+")
_host_lock = threading.Lock()
_host_sems: dict[str, threading.Semaphore] = {}


# ---------------------------------------------------------------- table parsing

def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def _url_of(cell: str) -> str:
    m = LINK.search(cell)
    if m:
        return m.group(2).strip("<>")
    m = BARE_URL.search(cell)
    return m.group(0).rstrip(".,;") if m else ""


def _title_of(cell: str) -> str:
    m = LINK.search(cell)
    text = m.group(1) if m else cell
    return re.sub(r"[*_`]", "", text).strip()


def parse_table(text: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    header: dict[str, int] | None = None
    missing: list[str] = REQUIRED
    for lineno, line in enumerate(text.splitlines(), 1):
        if "|" not in line:
            header = None
            continue
        cells = _cells(line)
        lowered = [c.lower() for c in cells]
        if "paper" in lowered and "problem" in lowered:
            header = {name: i for i, name in enumerate(lowered)}
            missing = [c for c in REQUIRED if c not in header]
            continue
        if header is None or all(SEPARATOR.match(c) or not c for c in cells):
            continue

        def get(name: str) -> str:
            i = header.get(name)
            return cells[i] if i is not None and i < len(cells) else ""

        rows.append({
            "line": lineno,
            "title": _title_of(get("paper")),
            "year": get("year"),
            "venue": get("venue"),
            "url": _url_of(get("url")),
            "url_cell": get("url"),
            "arxiv": _url_of(get("arxiv")),
            "arxiv_cell": get("arxiv"),
            "problem": get("problem"),
        })
    return rows, missing


# ---------------------------------------------------------------- text matching

def norm(title: str) -> str:
    t = unicodedata.normalize("NFKD", html.unescape(title))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"\$[^$]*\$", " ", t)          # inline math
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def same_title(expected: str, found: str) -> bool:
    a, b = norm(expected), norm(found)
    if not a or not b:
        return False
    if a == b or (len(a) > 20 and (a in b or b in a)):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


# ---------------------------------------------------------------- network

def _sem(url: str) -> threading.Semaphore:
    host = urllib.parse.urlsplit(url).netloc.lower()
    with _host_lock:
        return _host_sems.setdefault(host, threading.Semaphore(3))


def fetch(url: str, timeout: int = 30) -> str:
    """Return the page text, or raise RuntimeError with a short reason."""
    last = "no response"
    for attempt in range(3):
        try:
            with _sem(url):
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read(2_000_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (404, 410):
                raise RuntimeError(last)
            if e.code in (401, 403):
                break
        except Exception as e:  # timeouts, SSL, connection resets
            last = f"{type(e).__name__}: {e}"[:120]
        time.sleep(1.5 * (attempt + 1))
    curl = shutil.which("curl")
    if curl:  # some hosts reject urllib's TLS fingerprint but accept curl
        with _sem(url):
            proc = subprocess.run(
                [curl, "-sS", "-L", "--fail", "--max-time", str(timeout), "-A", USER_AGENT, url],
                capture_output=True,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout[:2_000_000].decode("utf-8", "replace")
        if proc.returncode == 22 and b"404" in proc.stderr:
            raise RuntimeError("HTTP 404")
    raise RuntimeError(last)


META = [
    re.compile(r'<meta[^>]+name=["\']citation_title["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_title["\']', re.I),
    re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', re.I),
    re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S),
]


def page_titles(page: str) -> list[str]:
    found = []
    for rx in META:
        m = rx.search(page)
        if m:
            found.append(html.unescape(re.sub(r"\s+", " ", m.group(1))).strip())
    return found


def arxiv_titles(ids: list[str]) -> dict[str, str]:
    """One API call per 50 ids: far gentler on arXiv than opening every abs page."""
    out: dict[str, str] = {}
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        url = "https://export.arxiv.org/api/query?max_results=50&id_list=" + ",".join(chunk)
        try:
            root = ET.fromstring(fetch(url, timeout=60))
        except Exception as e:
            print(f"  arXiv API failed ({e}); those rows will be listed as unverified", file=sys.stderr)
            continue
        for entry in root.findall("a:entry", ns):
            m = re.search(r"abs/(\d{4}\.\d{4,5})", entry.findtext("a:id", "", ns))
            title = " ".join((entry.findtext("a:title", "", ns) or "").split())
            if m and title and title.lower() != "error":
                out[m.group(1)] = title
        time.sleep(3)
    return out


# ---------------------------------------------------------------- checks

def check_static(rows: list[dict], minimum: int) -> tuple[list[dict], list[dict]]:
    errors, warnings = [], []

    def add(bucket, row, msg):
        bucket.append({"line": row["line"], "title": row["title"], "issue": msg})

    seen_title: dict[str, int] = {}
    seen_arxiv: dict[str, int] = {}
    for r in rows:
        if not r["title"]:
            add(errors, r, "Paper cell has no title")
        if not re.fullmatch(r"(19|20)\d\d", r["year"]):
            add(errors, r, f"Year is not a 4-digit year: {r['year']!r}")
        if r["venue"].lower() in EMPTY:
            add(errors, r, "Venue is empty (write arXiv for preprints)")
        if len(r["problem"].split()) < 6:
            add(errors, r, "Problem statement is missing or too short to say what the problem is")
        if not r["url"] and not r["arxiv"]:
            add(errors, r, "no link at all: needs an official URL, an arXiv URL, or both")
        if r["url_cell"].lower() not in EMPTY and not r["url"]:
            add(errors, r, f"URL cell is not a link: {r['url_cell']!r}")
        if r["arxiv_cell"].lower() not in EMPTY and not ARXIV_ID.search(r["arxiv"]):
            add(errors, r, f"arXiv cell is not an arxiv.org/abs/ID link: {r['arxiv_cell']!r}")
        if r["url"] and ARXIV_ID.search(r["url"]):
            add(errors, r, "URL column holds an arXiv link; it is for the official venue page (leave it — if there is none)")
        is_preprint = r["venue"].lower() in {"arxiv", "preprint", "arxiv preprint"}
        if not is_preprint and not r["url"]:
            add(warnings, r, f"Venue is {r['venue']} but there is no official URL; find the proceedings page")
        if is_preprint and r["url"]:
            add(warnings, r, "Venue is arXiv but an official URL is given; the venue is probably known")
        if SURVEY.search(r["title"]):
            add(warnings, r, "title reads like a survey / review / position paper; these should not be listed")
        key = norm(r["title"])
        if key and key in seen_title:
            add(errors, r, f"duplicate of line {seen_title[key]} (same title)")
        seen_title.setdefault(key, r["line"])
        m = ARXIV_ID.search(r["arxiv"])
        if m:
            if m.group(1) in seen_arxiv:
                add(errors, r, f"duplicate of line {seen_arxiv[m.group(1)]} (same arXiv id)")
            seen_arxiv.setdefault(m.group(1), r["line"])
    if len(rows) < minimum:
        warnings.append({"line": None, "title": None, "issue": f"only {len(rows)} papers; the target is {minimum}+"})
    return errors, warnings


def check_links(rows: list[dict], workers: int) -> tuple[list[dict], list[dict]]:
    errors, unverified = [], []
    lock = threading.Lock()

    def add(bucket, row, msg):
        with lock:
            bucket.append({"line": row["line"], "title": row["title"], "issue": msg})

    ids = sorted({m.group(1) for r in rows if (m := ARXIV_ID.search(r["arxiv"]))})
    titles = arxiv_titles(ids) if ids else {}
    for r in rows:
        m = ARXIV_ID.search(r["arxiv"])
        if not m:
            continue
        found = titles.get(m.group(1))
        if found is None:
            add(unverified, r, f"arXiv {m.group(1)}: no answer from the arXiv API (wrong id, or API unavailable)")
        elif not same_title(r["title"], found):
            add(errors, r, f"arXiv {m.group(1)} is a different paper: {found!r}")

    def one(r: dict) -> None:
        try:
            page = fetch(r["url"])
        except RuntimeError as e:
            reason = str(e)
            bucket = errors if reason in ("HTTP 404", "HTTP 410") else unverified
            add(bucket, r, f"URL {r['url']} -> {reason}")
            return
        found = page_titles(page)
        if any(BOT_WALL.search(t) for t in found):
            # OpenReview and some publishers answer scripts with a browser check.
            add(unverified, r, f"URL {r['url']} is behind a browser check; cannot be checked by script")
            return
        if any(same_title(r["title"], t) for t in found):
            return
        if not found or norm(r["title"]) in norm(page):
            if not found:
                add(unverified, r, f"URL {r['url']} opened but exposes no title to compare")
            return
        add(errors, r, f"URL {r['url']} shows a different title: {found[0]!r}")

    todo = [r for r in rows if r["url"]]
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for i, _ in enumerate(pool.map(one, todo), 1):
            if i % 10 == 0 or i == len(todo):
                print(f"  checked {i}/{len(todo)} official URLs", file=sys.stderr)
    return errors, unverified


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("table", help="path to papers.md")
    ap.add_argument("--min", type=int, default=30, help="minimum number of papers expected (default 30)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--offline", action="store_true", help="format checks only, no network")
    args = ap.parse_args()

    try:
        text = open(args.table, encoding="utf-8").read()
    except OSError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    rows, missing = parse_table(text)
    if missing or not rows:
        print(json.dumps({"error": "no usable table found", "missing_columns": missing,
                          "expected_columns": "Paper | Year | Venue | URL | arXiv | Problem"}))
        return 2

    errors, warnings = check_static(rows, args.min)
    unverified: list[dict] = []
    if not args.offline:
        link_errors, unverified = check_links(rows, args.workers)
        errors += link_errors
    key = lambda d: (d["line"] or 0)
    report = {
        "table": args.table,
        "papers": len(rows),
        "with_official_url": sum(bool(r["url"]) for r in rows),
        "with_arxiv": sum(bool(r["arxiv"]) for r in rows),
        "errors": sorted(errors, key=key),
        "warnings": sorted(warnings, key=key),
        "unverified": sorted(unverified, key=key),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
