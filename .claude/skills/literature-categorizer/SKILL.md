---
name: literature-categorizer
description: "Step 2 of the literature-review pipeline (collect → categorize → download → slides). Groups the papers in reference/papers.md by the problem each one focuses on and writes reference/index.md: a category table (name, folder short name, problem focus) and a paper table with each paper's category and PDF file path."
disable-model-invocation: true
argument-hint: "[path/to/papers.md] (default: ./reference/papers.md)"
---

# Literature Categorizer

`papers.md` is a list of papers from a research area the user is new to. This
step turns the list into a map: a small set of categories, each one a **problem
the field is struggling with**, with every paper placed under the problem it
works on. Reading the category table alone should tell a newcomer what is
unsolved in this area and where the effort is going.

The user does not know the papers, so they cannot review the grouping. Nobody
checks this taxonomy before the PDFs are filed into its folders and the slides
are organized around it, which is why the workflow below checks itself twice.

Input: $ARGUMENTS (if empty, `./reference/papers.md`). Output: `index.md` in the
same directory.

## Problem, not topic or method

Two papers belong together when they are trying to fix or understand the same
thing — not when they share a technique, a model, or a keyword.

- A paper that uses sparse autoencoders to find language-specific features and a
  paper that uses probing for the same purpose share a category; two papers that
  both use sparse autoencoders for unrelated questions do not.
- A benchmark or analysis paper goes under the problem it measures or explains,
  next to the methods that attack that problem. Do not make a "Benchmarks" or
  "Analysis" category: that sorts by paper type and hides what each one is about.

Name each category as the problem itself, so that the name alone says what is wrong:

| Topic or method (avoid) | Problem (use) |
| --- | --- |
| Knowledge editing | Edits do not propagate across languages |
| Memory architectures | Agents lose information beyond the context window |
| Evaluation | Existing benchmarks cannot tell memorization from reasoning |

## Workflow

### 1. Read every problem statement

Read the whole table before forming any category. The `Problem` column is the
main input. Where a statement is vague, describes the contribution instead of
the problem, or could fit two different problems, open the paper's abstract
(the arXiv or URL link) and settle what the paper is really about. A few lookups
here are cheap; a misplaced paper ends up in the wrong folder and the wrong
slide section.

### 2. Draft the categories from the papers

Build the categories bottom-up: cluster the problem statements, then name each
cluster. Do not start from a textbook outline of the field and force papers
into it — the point is to show what *these* papers are working on.

For each category write:

- **Category** — the problem, as a short phrase (see the table above).
- **Short name** — 1–3 lowercase words joined by underscores, e.g. `edit_propagation`. It becomes the folder name under `reference/`.
- **Problem focus** — one or two sentences: what is broken or unknown, and why it matters. Write it for someone who has not read any of the papers; this text is reused as-is on the overview slides.

For 30–40 papers, 5–8 categories usually reads well. Fewer and distinct problems
are being lumped together; more and the map stops being an overview.

### 3. Assign every paper to exactly one category

Every paper in `papers.md` gets a category — surveys were already left out when
the list was collected, so nothing here is dropped. A paper that touches two
problems goes under the one its main contribution addresses.

Test each placement by reading it as a sentence: "*<paper>* works on the problem
that *<problem focus>*." If that sentence is a stretch, the paper is in the
wrong place or the category is drawn wrong.

### 4. Check the taxonomy, then revise it

Look at the result as a whole and fix what you find:

- **A category much larger than the rest** (more than about a third of the papers) usually hides two problems. Split it.
- **A category with one paper** — merge it into the nearest problem, unless that paper really stands alone, in which case keep it.
- **"Other" / "Miscellaneous"** is not a problem. Place those papers properly, redrawing category boundaries if needed.
- **Overlapping categories** — if you cannot say in one sentence why a paper belongs in A rather than B, the boundary is unclear. Sharpen the two problem-focus texts until it is.
- **Names that are still topics or methods** — rename them as problems.

Then get a second opinion that has not seen your assignments. If subagents are
available, give one only the category table (names and problem focus) and the
list of papers with their problem statements, and ask it to assign each paper
independently. Compare with yours. Where the two disagree, either the paper is
ambiguous (re-read its abstract and decide) or the category definitions overlap
(fix the definitions). Agreement on nearly every paper means the categories are
clear enough for a reader to use. Without subagents, do the same pass yourself
from the definitions alone, without looking at your earlier assignments.

### 5. Write index.md

Write `index.md` next to `papers.md` in exactly this shape; the download and
slide steps parse it:

```markdown
# Index: <research area>

<N> papers in <K> categories · categorized <YYYY-MM-DD>

## Categories

| Category | Short name | Problem focus | Papers |
| --- | --- | --- | --- |
| Edits do not propagate across languages | edit_propagation | A fact edited in one language often stays unchanged when the model is asked in another, so multilingual models end up holding contradictory knowledge. | 12 |

## Papers

| Paper | Year | Venue | Category | URL | arXiv | File |
| --- | --- | --- | --- | --- | --- | --- |
| BMIKE-53: Investigating Cross-Lingual Knowledge Editing with In-Context Learning | 2025 | ACL | Edits do not propagate across languages | https://aclanthology.org/2025.acl-long.798/ | https://arxiv.org/abs/2406.17764 | `edit_propagation/2025_bmike53_acl.pdf` |
```

- Copy Paper, Year, Venue, URL and arXiv from `papers.md` unchanged. The title is the key that links the two files.
- **Category** in the paper table is spelled exactly as in the category table.
- **File** is `<short name>/<year>_<paper short name>_<venue>.pdf`, all lowercase with underscores, unique per paper:
  - *paper short name* — the name researchers use for the paper: its method or benchmark name if it has one (`bmike53`, `mlake`, `memgpt`), otherwise its core idea in 1–3 words (`null_space_editing`).
  - *venue* — the conference abbreviation: `acl`, `emnlp`, `neurips`, `iclr`. Findings and workshop papers use the host conference (`Findings of ACL` → `acl`); preprints use `arxiv`.
- Order the category table from the most central problem to the most peripheral, and the paper table by category in that same order, then by year.

If `index.md` already exists and is not empty, do not overwrite it silently —
PDFs may already be filed under its folder names. Say what is there and ask.

### 6. Run the check

```bash
python3 <this-skill-dir>/scripts/check_index.py <path/to/index.md>
```

It compares the index with `papers.md` (every paper present exactly once) and
checks the table format, the category names, the file paths and the paper
counts. Fix every entry under `errors` and run it again until there are none.
Entries under `warnings` are about category size and naming: act on them or
keep the category for a reason you can state in the report.

### 7. Report

Show the category table — it is the result the user came for — and add only
what they need to know beyond it:

```
reference/index.md — 34 papers in 6 categories

<the category table>

Notes: <judgment calls worth knowing — a paper that could have gone either way and where it went,
a single-paper category that was kept and why, disagreements from the second-opinion pass>
```
