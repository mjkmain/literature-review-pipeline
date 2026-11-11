#!/usr/bin/env python3
"""Download every paper listed in an index.md table, in parallel.

The index is a Markdown table with the columns ``Paper``, ``URL``, ``arXiv``
and ``File`` (``Year``, ``Venue`` and ``Category`` are not needed to download):

    | Paper | Year | Venue | Category | URL | arXiv | File |
    | --- | --- | --- | --- | --- | --- | --- |
    | Title | 2025 | ACL | Some problem | https://aclanthology.org/2025.acl-long.1/ | https://arxiv.org/abs/2501.00001 | `some_problem/2025_x_acl.pdf` |

For each row the official ``URL`` is tried first, then the ``arXiv`` link, then
an exact-title lookup. Each PDF is saved at its ``File`` path, relative to the
index's directory (override with --root), so the folder part of ``File`` is
what sorts papers into category folders. Files that already exist as valid PDFs
are skipped, so re-running only fetches what is still missing.

Progress goes to stderr; a JSON summary goes to stdout.

Usage
-----
python3 fetch_index.py reference/index.md
python3 fetch_index.py reference/index.md --dry-run     # show the plan, no network
python3 fetch_index.py reference/index.md --workers 12 --root /some/dir

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (compatible; paper-index-downloader/1.0)"
MIN_PDF_BYTES = 10_240
MAX_BYTES = 200 * 1024 * 1024
RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF = (2, 6, 15)
DOWNLOAD_TIMEOUT = [600]  # seconds allowed for one whole file; set by --timeout

# Concurrent connections allowed per host. arXiv asks for gentle use.
HOST_LIMITS = {"arxiv.org": 2, "export.arxiv.org": 1, "api.semanticscholar.org": 1}
DEFAULT_HOST_LIMIT = 4

_host_sems: dict[str, threading.Semaphore] = {}
_host_lock = threading.Lock()
_arxiv_api_lock = threading.Lock()
_arxiv_api_last = [0.0]
_use_curl = threading.Event()
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Index parsing
# --------------------------------------------------------------------------

_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_LINK = re.compile(r"\[(?P<text>.+)\]\((?P<url>[^()\s]+(?:\([^()\s]*\)[^()\s]*)*)\)")
_SEPARATOR = re.compile(r"^:?-{2,}:?$")
_ARXIV_HOST = re.compile(r"^https?://(?:www\.|export\.)?arxiv\.org/", re.I)


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(line)]


def _parse_paper_cell(cell: str) -> tuple[str, str | None, str]:
    """Return (title, url or None, authors)."""
    m = _LINK.match(cell)
    if m and m.group("url").startswith(("http://", "https://")):
        title, url, rest = m.group("text"), m.group("url"), cell[m.end():].strip()
    else:
        title, url, rest = cell, None, ""
        # "Title (Authors et al.)" without a link: peel the trailing parenthetical.
        tail = re.search(r"\s\(([^()]*)\)\s*$", cell)
        if tail:
            title, rest = cell[: tail.start()], f"({tail.group(1)})"
    authors = rest[1:-1].strip() if rest.startswith("(") and rest.endswith(")") else rest
    return title.strip().strip("*_ "), url, authors


_BARE_URL = re.compile(r"https?://[^\s|<>)]+")


def _parse_url_cell(cell: str) -> str | None:
    """A cell holding a bare URL or a [text](url) link; '—' or empty means none."""
    m = _LINK.search(cell)
    if m and m.group("url").startswith(("http://", "https://")):
        return m.group("url")
    m = _BARE_URL.search(cell)
    return m.group(0).rstrip(".,;") if m else None


def _parse_file_cell(cell: str) -> str:
    m = _LINK.match(cell)
    path = m.group("url") if m else cell
    path = urllib.parse.unquote(path.strip().strip("`").strip())
    return path


def parse_index(text: str) -> list[dict]:
    """Extract rows from every table in the file that has Paper and File columns."""
    rows: list[dict] = []
    header: dict[str, int] | None = None
    for line in text.splitlines():
        if "|" not in line:
            header = None
            continue
        cells = _cells(line)
        lowered = [c.lower() for c in cells]
        if "paper" in lowered and "file" in lowered:
            header = {name: i for i, name in enumerate(lowered)}
            continue
        if header is None or all(_SEPARATOR.match(c) or not c for c in cells):
            continue

        def get(name: str) -> str:
            i = header.get(name)
            return cells[i] if i is not None and i < len(cells) else ""

        title, paper_link, authors = _parse_paper_cell(get("paper"))
        if not title:
            continue
        # Older indexes keep the link inside the Paper cell instead of a URL column.
        url, arxiv = _parse_url_cell(get("url")) or paper_link, _parse_url_cell(get("arxiv"))
        if url and _ARXIV_HOST.search(url) and not arxiv:
            url, arxiv = None, url
        rows.append(
            {
                "title": title,
                "url": url,
                "arxiv": arxiv,
                "authors": authors,
                "year": get("year"),
                "venue": get("venue"),
                "category": get("category"),
                "file": _parse_file_cell(get("file")),
            }
        )
    return rows


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _sem_for(url: str) -> threading.Semaphore:
    host = urllib.parse.urlsplit(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    with _host_lock:
        if host not in _host_sems:
            _host_sems[host] = threading.Semaphore(HOST_LIMITS.get(host, DEFAULT_HOST_LIMIT))
        return _host_sems[host]


class FetchError(Exception):
    pass


def _curl_get(url: str, timeout: int) -> tuple[bytes, str]:
    curl = shutil.which("curl")
    if not curl:
        raise FetchError("SSL verification failed and curl is unavailable")
    proc = subprocess.run(
        [curl, "-sS", "-L", "--fail", "--max-time", str(timeout), "-A", USER_AGENT,
         "-w", "\n%{content_type}", url],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise FetchError(proc.stderr.decode("utf-8", "replace").strip() or f"curl exit {proc.returncode}")
    body, _, ctype = proc.stdout.rpartition(b"\n")
    return body, ctype.decode("ascii", "replace")


def http_get(url: str, timeout: int | None = None) -> tuple[bytes, str]:
    """GET with per-host concurrency limits and retries. Returns (body, content_type)."""
    timeout = timeout or DOWNLOAD_TIMEOUT[0]
    last = "unknown error"
    for attempt in range(len(BACKOFF) + 1):
        wait = BACKOFF[min(attempt, len(BACKOFF) - 1)]
        try:
            with _sem_for(url):
                if _use_curl.is_set():
                    return _curl_get(url, timeout)
                req = urllib.request.Request(
                    url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8"}
                )
                # `timeout` only bounds each socket read, so a server that trickles
                # bytes could hold a worker forever; `deadline` bounds the whole body.
                started = time.monotonic()
                with urllib.request.urlopen(req, timeout=min(timeout, 60)) as resp:
                    chunks, size = [], 0
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise FetchError("response larger than 200 MB")
                        if time.monotonic() - started > timeout:
                            total = resp.headers.get("Content-Length") or "?"
                            raise FetchError(
                                f"too slow: {size // 1024} KB of {total} bytes in {timeout}s "
                                "(raise --timeout or download manually)"
                            )
                    return b"".join(chunks), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code not in RETRY_STATUS:
                raise FetchError(last) from exc
            retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
            if retry_after.isdigit():
                wait = min(int(retry_after), 30)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                # Common on python.org macOS builds without installed certs.
                _use_curl.set()
                continue
            last = f"network error: {exc.reason}"
        except (TimeoutError, ConnectionError, OSError) as exc:
            last = f"network error: {exc}"
        if attempt < len(BACKOFF):
            time.sleep(wait)
    raise FetchError(f"{last} (after {len(BACKOFF) + 1} attempts)")


# --------------------------------------------------------------------------
# URL resolution
# --------------------------------------------------------------------------


def direct_pdf_url(url: str) -> str | None:
    """Map a known landing-page URL to its PDF URL without any network call."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    path = parts.path

    if path.lower().endswith(".pdf"):
        return url
    if host == "aclanthology.org":
        return f"https://aclanthology.org/{path.strip('/')}.pdf"
    if host in ("arxiv.org", "export.arxiv.org"):
        m = re.match(r"^/(?:abs|pdf|html)/(.+?)/?$", path)
        if m:
            return f"https://arxiv.org/pdf/{m.group(1)}"
    if host == "openreview.net":
        paper_id = urllib.parse.parse_qs(parts.query).get("id", [None])[0]
        if paper_id:
            return f"https://openreview.net/pdf?id={paper_id}"
    if host == "proceedings.mlr.press":
        m = re.match(r"^/(v\d+)/([^/]+)\.html$", path)
        if m:
            return f"https://proceedings.mlr.press/{m.group(1)}/{m.group(2)}/{m.group(2)}.pdf"
    if host in ("proceedings.neurips.cc", "papers.nips.cc") and "/hash/" in path:
        return urllib.parse.urlunsplit(
            parts._replace(
                path=path.replace("/hash/", "/file/")
                .replace("-Abstract", "-Paper")
                .replace(".html", ".pdf")
            )
        )
    if host == "ojs.aaai.org" and "/article/view/" in path:
        return None  # needs the landing page (citation_pdf_url)
    return None


_META_PDF = re.compile(
    r"""<meta[^>]+name=["']citation_pdf_url["'][^>]+content=["']([^"']+)["']"""
    r"""|<meta[^>]+content=["']([^"']+)["'][^>]+name=["']citation_pdf_url["']""",
    re.I,
)
_OPENREVIEW = re.compile(r"https?://openreview\.net/(?:forum|pdf)\?id=([\w-]+)")
_ARXIV_LINK = re.compile(r"https?://arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})")


def pdf_url_from_landing(html: str, base: str) -> str | None:
    """Find a PDF link in a landing page: scholar meta tag, then OpenReview/arXiv links."""
    m = _META_PDF.search(html)
    if m:
        return urllib.parse.urljoin(base, (m.group(1) or m.group(2)).replace("&amp;", "&"))
    m = _OPENREVIEW.search(html)
    if m:
        return f"https://openreview.net/pdf?id={m.group(1)}"
    m = _ARXIV_LINK.search(html)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    return None


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def arxiv_title_lookup(title: str) -> str | None:
    """Exact-title lookup on the arXiv API. Returns a PDF URL or None."""
    query = re.sub(r"[^\w\s-]", " ", title)
    query = re.sub(r"\s+", " ", query).strip()
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": f'ti:"{query}"', "max_results": 5}
    )
    with _arxiv_api_lock:  # arXiv asks for one API request every 3 seconds
        gap = 3.0 - (time.monotonic() - _arxiv_api_last[0])
        if gap > 0:
            time.sleep(gap)
        try:
            body, _ = http_get(url, timeout=30)
        finally:
            _arxiv_api_last[0] = time.monotonic()
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in ET.fromstring(body).findall(f"{ns}entry"):
        found = entry.findtext(f"{ns}title", "") or ""
        if _norm_title(found) == _norm_title(title):
            arxiv_id = (entry.findtext(f"{ns}id", "") or "").rsplit("/abs/", 1)[-1]
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
            if arxiv_id:
                return f"https://arxiv.org/pdf/{arxiv_id}"
    return None


def s2_title_lookup(title: str) -> str | None:
    """Exact-title lookup on Semantic Scholar. Returns a PDF URL or None."""
    url = "https://api.semanticscholar.org/graph/v1/paper/search/match?" + urllib.parse.urlencode(
        {"query": title, "fields": "title,openAccessPdf,externalIds"}
    )
    body, _ = http_get(url, timeout=30)
    for paper in json.loads(body).get("data") or []:
        if _norm_title(paper.get("title") or "") != _norm_title(title):
            continue
        ids = paper.get("externalIds") or {}
        if ids.get("ArXiv"):
            return f"https://arxiv.org/pdf/{ids['ArXiv']}"
        if ids.get("ACL"):
            return f"https://aclanthology.org/{ids['ACL']}.pdf"
        oa = (paper.get("openAccessPdf") or {}).get("url")
        if oa:
            return oa
    return None


# --------------------------------------------------------------------------
# Per-paper work
# --------------------------------------------------------------------------


def is_pdf(data: bytes) -> bool:
    return len(data) >= MIN_PDF_BYTES and b"%PDF" in data[:1024]


def existing_ok(path: Path) -> bool:
    try:
        if path.stat().st_size < MIN_PDF_BYTES:
            return False
        with path.open("rb") as fh:
            return b"%PDF" in fh.read(1024)
    except OSError:
        return False


def _try_pdf(url: str) -> tuple[bytes | None, str]:
    """Fetch url; return (pdf bytes, '') or (None, reason). Follows one landing-page hop."""
    try:
        data, ctype = http_get(url)
    except FetchError as exc:
        return None, str(exc)
    if is_pdf(data):
        return data, ""
    if b"%PDF" in data[:1024]:
        return None, f"PDF too small ({len(data)} bytes)"
    if "html" in ctype.lower() or data[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        nxt = pdf_url_from_landing(data.decode("utf-8", "replace"), url)
        if nxt and nxt != url:
            try:
                data, _ = http_get(nxt)
            except FetchError as exc:
                return None, f"{nxt}: {exc}"
            if is_pdf(data):
                return data, ""
            return None, f"{nxt} did not return a PDF"
        return None, "landing page has no PDF link"
    return None, f"not a PDF (content-type: {ctype or 'unknown'})"


def fetch_one(row: dict, root: Path) -> dict:
    result = {k: row[k] for k in ("title", "url", "arxiv", "file")}
    if not row["file"]:
        return {**result, "status": "failed", "reason": "File column is empty"}
    dest = (root / row["file"]).resolve()
    if root.resolve() not in dest.parents:
        return {**result, "status": "failed", "reason": "File path escapes the root directory"}
    if existing_ok(dest):
        return {**result, "status": "skipped"}

    attempts: list[str] = []
    candidates: list[tuple[str, str]] = []  # (how, url)
    if row["url"]:
        candidates.append(("official URL", direct_pdf_url(row["url"]) or row["url"]))
    if row["arxiv"]:
        candidates.append(("arXiv link", direct_pdf_url(row["arxiv"]) or row["arxiv"]))

    data = None
    how = ""
    for how, url in candidates:
        data, reason = _try_pdf(url)
        if data:
            break
        attempts.append(f"{url}: {reason}")

    if not data:
        # Neither link in the index worked: look the paper up by exact title.
        for how, lookup in (("arXiv title match", arxiv_title_lookup), ("Semantic Scholar title match", s2_title_lookup)):
            try:
                url = lookup(row["title"])
            except (FetchError, ET.ParseError, ValueError) as exc:
                attempts.append(f"{how}: {exc}")
                continue
            if not url:
                attempts.append(f"{how}: no exact match")
                continue
            data, reason = _try_pdf(url)
            if data:
                break
            attempts.append(f"{url}: {reason}")

    if not data:
        return {**result, "status": "failed", "reason": "; ".join(attempts) or "no URL"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return {**result, "status": "downloaded", "source": url, "via": how, "size_kb": len(data) // 1024}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download the papers listed in an index.md table.")
    ap.add_argument("index", help="Path to index.md")
    ap.add_argument("--root", help="Directory that File paths are relative to (default: the index's directory)")
    ap.add_argument("--workers", type=int, default=8, help="Parallel downloads (default: 8)")
    ap.add_argument("--timeout", type=int, default=600, help="Seconds allowed per file (default: 600)")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan without downloading")
    args = ap.parse_args(argv)

    DOWNLOAD_TIMEOUT[0] = max(10, args.timeout)
    index = Path(args.index)
    if not index.is_file():
        print(json.dumps({"error": f"index not found: {index}"}))
        return 2
    root = Path(args.root) if args.root else index.parent
    rows = parse_index(index.read_text(encoding="utf-8"))
    if not rows:
        print(json.dumps({"error": "no table rows with Paper and File columns found", "index": str(index)}))
        return 2

    # Two rows pointing at the same file would race; keep the first.
    seen: dict[str, str] = {}
    duplicates = []
    unique = []
    for row in rows:
        if row["file"] and row["file"] in seen:
            duplicates.append({"file": row["file"], "title": row["title"], "first": seen[row["file"]]})
            continue
        seen[row["file"]] = row["title"]
        unique.append(row)

    if args.dry_run:
        plan = []
        for row in unique:
            exists = bool(row["file"]) and existing_ok(root / row["file"])
            plan.append(
                {
                    "title": row["title"],
                    "file": row["file"],
                    "exists": exists,
                    "try_in_order": [
                        direct_pdf_url(u) or f"(landing page) {u}" for u in (row["url"], row["arxiv"]) if u
                    ] + ["(title lookup)"],
                }
            )
        print(json.dumps({"root": str(root), "total": len(plan), "duplicates": duplicates, "plan": plan},
                         ensure_ascii=False, indent=2))
        return 0

    started = time.monotonic()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(fetch_one, row, root): row for row in unique}
        for done, fut in enumerate(as_completed(futures), 1):
            try:
                res = fut.result()
            except Exception as exc:  # keep one bad row from sinking the batch
                row = futures[fut]
                res = {"title": row["title"], "url": row["url"], "arxiv": row["arxiv"], "file": row["file"],
                       "status": "failed", "reason": f"unexpected error: {exc!r}"}
            results.append(res)
            mark = {"downloaded": "ok  ", "skipped": "skip", "failed": "FAIL"}[res["status"]]
            log(f"[{done}/{len(unique)}] {mark} {res['file'] or res['title']}")

    order = {row["title"]: i for i, row in enumerate(unique)}
    results.sort(key=lambda r: order.get(r["title"], 0))
    by = lambda s: [r for r in results if r["status"] == s]  # noqa: E731
    downloaded, skipped, failed = by("downloaded"), by("skipped"), by("failed")
    summary = {
        "root": str(root),
        "total": len(unique),
        "downloaded": len(downloaded),
        "skipped_existing": len(skipped),
        "failed": len(failed),
        "seconds": round(time.monotonic() - started, 1),
        # The official page gave no PDF, so the arXiv version was saved instead.
        # It can differ from the published camera-ready version.
        "arxiv_instead_of_official": [
            {"title": r["title"], "file": r["file"], "official_url": r["url"], "source": r["source"]}
            for r in downloaded
            if r["via"] == "arXiv link" and r["url"]
        ],
        # Rows fetched by title lookup rather than a link from the index: worth a glance.
        "resolved_by_title_lookup": [
            {"title": r["title"], "file": r["file"], "source": r["source"], "via": r["via"]}
            for r in downloaded
            if r["via"] not in ("official URL", "arXiv link")
        ],
        "failures": [{k: r[k] for k in ("title", "url", "arxiv", "file", "reason")} for r in failed],
        "duplicates": duplicates,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
