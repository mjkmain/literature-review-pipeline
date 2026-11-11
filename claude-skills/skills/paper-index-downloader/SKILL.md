---
name: paper-index-downloader
description: "Step 3 of the literature-review pipeline (collect → categorize → download → slides). Downloads every paper listed in reference/index.md into reference/<category short name>/, trying the official URL first and the arXiv link second, in parallel, skipping PDFs that are already there."
disable-model-invocation: true
argument-hint: "[path/to/index.md] (default: ./reference/index.md)"
allowed-tools: Bash(*), Read, Edit, Glob, WebSearch, WebFetch
---

# Paper Index Downloader

`index.md` already says which papers are wanted and where each PDF goes. The job
is only to turn that table into PDFs on disk, fast. There is nothing to search,
rank, or confirm — the index is the confirmation.

Index path: $ARGUMENTS (if empty, use `./reference/index.md`)

## Index format

The paper table written by the categorize step:

```markdown
| Paper | Year | Venue | Category | URL | arXiv | File |
| --- | --- | --- | --- | --- | --- | --- |
| BMIKE-53: Investigating Cross-Lingual Knowledge Editing with In-Context Learning | 2025 | ACL | Edits do not propagate across languages | https://aclanthology.org/2025.acl-long.798/ | https://arxiv.org/abs/2406.17764 | `edit_propagation/2025_bmike53_acl.pdf` |
| Some Preprint Title | 2026 | arXiv | Edits do not propagate across languages | — | https://arxiv.org/abs/2601.01234 | `edit_propagation/2026_some_preprint_arxiv.pdf` |
```

- **URL** — the paper's official page (ACL Anthology, conference proceedings); `—` if there is none.
- **arXiv** — the arXiv page; `—` if there is none.
- **File** — where the PDF goes, relative to the directory containing `index.md`. Its folder part is the category's short name, so following it is what produces `reference/<category short name>/<paper>.pdf`. Folders are created as needed.

The category table in the same file is ignored here.

## Workflow

### 1. Run the bundled script — once, for the whole index

```bash
python3 <this-skill-dir>/scripts/fetch_index.py path/to/index.md
```

`<this-skill-dir>` is the directory containing this SKILL.md. The script is
standard-library Python; nothing to install.

Do not download papers one at a time with separate tool calls, and do not read
the index into context first. One call per paper is what makes paper collection
slow; the script handles the whole table in a single call. For each row it:

- skips the File if it already exists as a valid PDF (so re-running is cheap and only fetches what is missing),
- tries the **official URL** first, turning the landing page into a PDF link by rule (ACL Anthology, OpenReview, PMLR, NeurIPS proceedings, direct `.pdf` links) or by reading the page for a PDF link,
- falls back to the **arXiv link** when the official page gives no PDF — this is the normal path for OpenReview-hosted papers (ICLR and others), because OpenReview turns away automated downloads,
- falls back to an exact-title lookup on arXiv, then Semantic Scholar, when neither link works,
- downloads in parallel with per-host limits and retries, checks each result is really a PDF (`%PDF` header, > 10 KB), and writes atomically.

Progress lines go to stderr; a JSON summary goes to stdout. Exit code is 0 when
everything is present, 1 when some rows failed.

Options: `--dry-run` (print the resolved plan, no network), `--workers N`
(default 8), `--timeout SEC` (per file, default 600), `--root DIR` (if File
paths are relative to somewhere other than the index's directory).

Give the Bash call a generous timeout (10 minutes), or run it in the background
for large indexes: a few proceedings PDFs are tens of MB and download slowly.
If the call is cut off, just run it again — finished files are skipped.

### 2. Handle only what the script could not

Look at `failures` in the summary. Each entry has `title`, `url`, `arxiv`,
`file`, and a `reason` listing what was tried. For those rows only:

1. Find a PDF URL yourself — WebSearch the exact title; check the venue's
   proceedings, the authors' pages.
2. Download to the exact File path and verify it is a PDF:
   ```bash
   curl -L --fail -o "<index-dir>/<file>" "<pdf-url>" && head -c 5 "<index-dir>/<file>"   # expect %PDF-
   ```
3. If no open-access PDF exists (paywalled, not yet published), leave it and
   say so. A wrong or partial paper on disk is worse than a missing one,
   because the slide step will trust the filename.

Special reasons:

- **`File column is empty`** — the row has no destination. Fill in the File
  cell following the convention the other rows use,
  `<category short name>/<year>_<paper short name>_<venue>.pdf` (all lowercase),
  then re-run the script.
- **`too slow`** — re-run with a larger `--timeout`.

Two lists in the summary are not failures but should be passed on to the user:

- `arxiv_instead_of_official` — the paper has an official URL but the PDF came
  from arXiv. The arXiv version can differ from the published one (earlier
  draft, different figure numbers).
- `resolved_by_title_lookup` — neither link in the index worked and the PDF was
  found by title. The match is exact on the normalized title, so it is normally
  the right paper, but the link in the index is probably wrong or missing.

Do not rewrite `index.md` beyond filling an empty File cell. It is the record
the other steps share; suggest the link you found instead of editing it in.

### 3. Report

Keep it short — the user wants to know whether the collection is complete:

```
Index: reference/index.md — 34 papers in 6 folders
Downloaded 31 · already present 2 · failed 1 (41s)

Failed:
- <title> → <file>: <one-line reason, and what you tried>

arXiv version saved instead of the official one:
- <title> → <file>

Found by title lookup (index links did not work):
- <title> → <source url>
```

Omit sections that are empty. If everything was already present, say so in one
line.
