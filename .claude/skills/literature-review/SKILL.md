---
name: literature-review
description: "Runs the whole literature-review pipeline end to end without stopping: collect papers on a research area, categorize them by problem, download the PDFs, and build the slide deck. Each step follows its own skill's instructions; the user is asked nothing between steps and gets one report at the end."
disable-model-invocation: true
argument-hint: "<research area> [— years: 2023-] [— min: 30] [— korean]"
allowed-tools: Bash(*), Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Agent
---

# Literature Review (full pipeline)

Request: $ARGUMENTS

The user is new to this area and cannot judge papers or categories along the
way, so the four steps run back to back with no questions in between. Each step
is written up as its own skill in `.claude/skills/`; this one runs them in order.

| # | Step skill | Input → output |
|---|---|---|
| 1 | `literature-collector` | area → `reference/papers.md` |
| 2 | `literature-categorizer` | `papers.md` → `reference/index.md` |
| 3 | `paper-index-downloader` | `index.md` → `reference/<category>/*.pdf` |
| 4 | `literature-slide-writer` | index + PDFs → `reference/summaries/`, `slide/<area-slug>-literature/<area-slug>_slide_en.pdf` |

## How to run a step

The step skills cannot be invoked from here (they are user-invoked only), so for
each step: **Read `<repo>/.claude/skills/<step skill>/SKILL.md` and carry out its
workflow yourself**, with these substitutions:

- `$ARGUMENTS` in that file means the values below, not this skill's request.
  - Step 1: `<research area> — years: <years> — min: <min>` (defaults: years `2023-`, min `30`).
  - Steps 2 and 3: empty (they default to `./reference/...`).
  - Step 4: empty, plus `korean` if this request contains `korean` / `한국어`.
- `<this-skill-dir>` means that step skill's directory.
- Where it says to **ask the user**, or to **tell/report something to the user**, do not stop: take the conservative choice, note it, and put it in the final report.

Finish each step's own checks before moving on — they are what keeps a bad
list from turning into 30 bad slides:

- Step 1 passes when `verify_papers.py` reports no `errors`.
- Step 2 passes when `check_index.py` reports no errors.
- Step 3 passes when the downloader's summary has been read; missing PDFs do not block step 4 (it skips them), but list them.
- Step 4 passes when `deck.py check` reports `"ok": true` and the contact sheets have been looked at.

If a step cannot pass after a genuine attempt (e.g. the area yields far fewer
papers than `min`, or the build keeps failing), stop there and report what is
done and what blocked it, rather than building on a broken input.

## Before step 1

1. **Environment.** If `<repo>/.venv` or `xelatex` (on PATH or in `~/.TinyTeX/bin/*/`) is missing, run `./setup.sh` in the repo root.
2. **Existing outputs.** This is the one place a question is allowed, because overwriting could lose work. If `reference/papers.md` exists, or `reference/index.md` is non-empty, ask once: resume from the first unfinished step, or start over. With nothing there (a fresh clone), start immediately. When resuming, a step is finished if its check above passes on the existing file; the slide step resumes on its own through `papers.json`.

## Context

The run is long. Keep the main thread for orchestration: the step skills
already push the heavy reading into subagents (thread searches in step 1, the
second-opinion pass in step 2, one agent per paper in step 4). Do not read PDFs
or paste whole tables into the main thread beyond what a step requires.

## Final report

One report, in the user's language:

```
Literature review: <area>
1. Papers   reference/papers.md — <N> papers (<years>); threads: ...
2. Taxonomy reference/index.md — <K> categories:
   <category> (<n>) · <category> (<n>) · ...
3. PDFs     <downloaded>/<N>; missing: <titles>
4. Slides   slide/<area-slug>-literature/<area-slug>_slide_en.pdf — <S> slides (<P> papers, <M> open problems)
            [<area-slug>_slide_ko.pdf if requested]
   Summaries reference/summaries/ — one per paper
Decisions taken without asking: <each, with the choice made>
Category doubts from per-paper agents: <paper → reason>
Unsure: <anything a step could not confirm>
```

Leave out empty lines. Do not commit or push anything unless asked.
