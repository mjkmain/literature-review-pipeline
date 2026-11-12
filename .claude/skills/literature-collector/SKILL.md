---
name: literature-collector
description: "Step 1 of the literature-review pipeline (collect → categorize → download → slides). Surveys a research area on the web and writes 30+ recent non-survey papers to reference/papers.md as a verified table: title, year, venue, official URL, arXiv URL, and the problem each paper focuses on."
disable-model-invocation: true
argument-hint: "[research area] [— years: 2023-] [— min: 30] [— out: reference/papers.md]"
---

# Literature Collector

The user is entering a research area they do not know yet. They cannot judge the
paper list themselves, and every later step — the problem taxonomy, the PDF
downloads, the slides — is built on it without another look. So two things
matter more than anything else here: the list has to **cover the field** rather
than one corner of it, and every row has to be **true** (a real paper, at that
link, at that venue).

Research area: $ARGUMENTS

Options, all optional: `years` (default: the last three years, plus the few
older papers that current work still builds on), `min` (default 30),
`out` (default `./reference/papers.md`).

## What counts as a paper to collect

Collect papers that set out a problem and then work on it: a new method, an
analysis, a benchmark or dataset. A benchmark paper has a problem too — the
thing that could not be measured before it.

Leave out surveys, reviews, tutorials and position papers. The next step sorts
papers by the problem each one tackles, and a survey tackles none, so it has
nowhere to go. Do read them while searching: a recent survey is the fastest map
of a field and its reference list is a good source of candidates.

Keep the area as broad as the user stated it. If they ask for "multilingual
language model analysis", do not quietly narrow it to the sub-topic with the
most search hits.

## Workflow

### 1. Map the field before choosing papers

Run a handful of searches (recent surveys, workshop pages, "awesome" lists,
the last two years of the main venues) and write down the 5–8 threads of work
that make up the area: the distinct problems people are working on. This map is
what makes the final list an overview; without it, the list drifts toward
whatever the first query returned.

### 2. Search each thread

Search the threads in parallel, one subagent per thread, if subagents are
available; otherwise work through them one by one. If the session offers a
built-in deep-research capability, it can be used for this stage instead — give
it the thread list and the row requirements below. Do not rely on any other
installed skill.

Give each subagent the thread, the year range, the exclusion rule, and the row
requirements, and ask for 8–12 candidates each so there is something to select
from. Each candidate comes back with: title, year, venue, official URL, arXiv
URL, problem statement, and one line on why it matters to the thread.

Whoever finds a paper opens its page before recording it. Titles, venues and
arXiv ids written from memory are often slightly wrong — a real title with
another paper's id, or a preprint remembered as an ACL paper — and a slightly
wrong row is worse than a missing one, because it looks fine.

### 3. Scan the proceedings by title

Search finds what is well linked; a paper can be published at a main venue and
still never surface in a query. So also go through the proceedings themselves:
the script downloads the title list of every paper at the venues that publish
theirs online (ACL Anthology — ACL, EMNLP, NAACL, EACL, AACL, COLING, TACL,
Findings, workshops — plus ICLR, ICML and NeurIPS) for the year range, and
matches each thread's keywords against all of them.

```bash
python3 <this-skill-dir>/scripts/scan_proceedings.py --years <years> \
  --thread "<thread name>=<regex>" --thread "<thread name>=<regex>" ...
```

One `--thread` per thread of the map. The regex is matched case-insensitively
against titles only, so write it from the words papers in that thread put in
their titles, with variants: `(cross-?lingual|multilingual).*(knowledge edit|model edit)|(knowledge edit|model edit).*(cross-?lingual|multilingual)`.
It returns title, venue, year and official URL per match (the first run downloads
the lists, about 20 MB; later runs use a 7-day cache).

- A thread with hundreds of matches has a regex that is too broad; one with none has one that is too narrow. Adjust and run again — it takes seconds.
- A match is a candidate, not a selection. Compare the matches with what the searches found; for each new one, open its page and read the abstract before it joins the candidates, and fill its row the same way as any other (step 4).
- The scan cannot replace the searches: it sees only titles, so it misses papers whose titles do not name the topic, and it does not cover arXiv-only work or other venues.
- If the downloads fail, say so in the report and continue with the search results.

### 4. Fill in each row from the paper's own page

**Venue and Year** — where and when the paper was published, taken from the
proceedings page. Many arXiv papers were later published: check the arXiv
"Comments" field and search the title on ACL Anthology / the conference site
before settling on `arXiv`. Write `arXiv` as the venue only when no published
version can be found, and use the arXiv year then. Mark Findings and workshops
as such (`Findings of ACL`, `NeurIPS Workshop`).

**URL** — the paper's official page at its venue:

| Venue | Official page |
| --- | --- |
| ACL, EMNLP, NAACL, EACL, COLING, TACL, Findings, ACL workshops | `aclanthology.org/<id>/` |
| NeurIPS | `proceedings.neurips.cc/...-Abstract...html` or `neurips.cc/virtual/<year>/poster/<n>` |
| ICML | `proceedings.mlr.press/v<vol>/<key>.html` or `icml.cc/virtual/<year>/poster/<n>` |
| ICLR | `iclr.cc/virtual/<year>/poster/<n>` or `openreview.net/forum?id=<id>` |
| Other venues | the proceedings or publisher page for the paper |

Write `—` when the paper is arXiv-only. An arXiv link never goes in this column.

**arXiv** — `https://arxiv.org/abs/<id>` whenever an arXiv version exists, also
when the URL column is filled; `—` otherwise. The download step falls back to
this link, and it needs it most for OpenReview-hosted papers (ICLR, some
NeurIPS/ICML), because OpenReview turns away automated downloads. For those
papers, look for the arXiv version with extra care.

**Problem** — one sentence on the problem the paper focuses on: what was
broken, missing or unknown before it. Take it from the abstract or introduction,
not from the title. Describe the problem, not the contribution, because the next
step groups papers by problem and "proposes X" tells it nothing:

- Contribution (not wanted): "Proposes BMIKE-53, a benchmark for cross-lingual in-context knowledge editing."
- Problem (wanted): "Knowledge edits are evaluated almost only in English, so it is unknown whether an edit made in one language holds when the model is queried in another."

### 5. Select

Merge the candidates and remove duplicates — a preprint and its published
version are one paper; keep the published venue and both links. Then choose the
final list:

- every thread from the map is represented, roughly in proportion to how active it is;
- within a thread, prefer papers that are peer-reviewed, recent, and that other papers in the thread build on or compare against;
- aim for `min` or more, but do not pad. If the area honestly yields fewer solid papers, stop there and say so — a tangential paper distorts the taxonomy built on this list.

### 6. Write the table

Write `out` (create the directory if needed) in exactly this shape; later steps
parse it:

```markdown
# Papers: <research area>

Collected <YYYY-MM-DD> · <N> papers · <year range>

| Paper | Year | Venue | URL | arXiv | Problem |
| --- | --- | --- | --- | --- | --- |
| BMIKE-53: Investigating Cross-Lingual Knowledge Editing with In-Context Learning | 2025 | ACL | https://aclanthology.org/2025.acl-long.798/ | https://arxiv.org/abs/2406.17764 | Knowledge edits are evaluated almost only in English, so it is unknown whether an edit made in one language holds when the model is queried in another. |
| Some Preprint Title | 2026 | arXiv | — | https://arxiv.org/abs/2601.01234 | ... |
```

One row per paper, the full title as plain text, bare links, no `|` inside a
cell. Order rows by thread, then by year, so neighbouring rows are related. Do
not add a category column: the threads were a search aid, and categorizing is
the next step's job, done from the problem statements.

If `out` already exists, do not overwrite it silently — it may be a list the
user has already built on. Say what is there and ask whether to replace it or
add to it.

### 7. Verify, then fix

```bash
python3 <this-skill-dir>/scripts/verify_papers.py <out> --min <min>
```

The script opens every link and compares the page's title with the row's. Its
JSON report has three lists:

- `errors` — dead links, links that lead to a different paper, duplicates, malformed cells. Fix every one: find the right link, or drop the paper if it cannot be confirmed to exist.
- `warnings` — survey-like titles, a venue without an official URL, too few papers. Look at each; fix it or keep it for a reason you can state.
- `unverified` — the site refused the script (OpenReview always does). Open these pages yourself to confirm the title; if you cannot, make sure the row has a verified arXiv link.

Run it again after fixing, until `errors` is empty. If papers were dropped and
the count fell below `min`, go back to the thinnest thread for replacements.

### 8. Report

Keep it short; the table is the deliverable.

```
reference/papers.md — 34 papers on <area> (2023–2026)
Threads: <thread> (7), <thread> (6), ...
Venues: 21 conference, 4 Findings/workshop, 9 arXiv-only
Proceedings scan: 112,000 titles, 41 matches, 9 papers added that the searches had missed
Verification: all links checked; 3 OpenReview pages confirmed by hand
Notes: <anything the user should know — a thread with few papers, papers dropped and why>
```
