# Brief for a per-paper agent

One agent per paper. The agent is told to read this file and is given the values
for the `<...>` fields in its prompt (they come from the paper's entry in
`papers.json`). `<repo>` is the repository root and `<deck>` the deck directory.

---

You are covering one paper of a literature review: a written summary of it, and
one slide drawn from that summary. The audience is a researcher who is new to
this area and has not read the paper. They should come away knowing what problem
the paper takes on and how it goes about it.

**Paper**: <title> (<venue> <year>)
**PDF**: <pdf>
**Category** (the problem this paper was filed under): <category> — <category problem focus>

**Write exactly these four files and touch nothing else** (other agents are
writing the neighbouring papers at the same time):

- summary: `<summary>`
- slide: `<deck>/<tex>`
- figure: `<deck>/<image>`
- notes: `<deck>/<notes>`

Tools: `PY=<repo>/.venv/bin/python`, `FIG=<repo>/.claude/skills/paper-figure-extractor/scripts/extract_figure.py`

## 1. Read the paper

Read the PDF itself — abstract, introduction, method, experimental setup,
results, and the limitations / conclusion sections; skip the appendix.
Everything you write must come from what you read in this PDF, not from what you
remember about the paper: memory mixes up versions and neighbouring papers.

## 2. Write the summary

Write `<summary>` now, while the paper is fresh, and before the slide: the slide
is then a selection from the summary, so the two cannot disagree. The summary
outlives this run — the open-problems section is written from all the summaries,
later edits and the Korean version use it instead of the PDF, and the user reads
it to go one level deeper than the slide. So it has to be accurate on its own.

```markdown
# <title>

<venue> <year> · <first author> et al. · <url or arXiv link>
Category: <category>

**TL;DR** — one sentence: the gap and what the paper does about it.

## Problem
What was broken, missing or unknown before this paper, and why existing work did
not cover it. 2–4 sentences.

## Method
The core idea, then how it works. For a benchmark: what it contains and how it was
built. For an analysis: what was measured and how. 3–6 sentences or bullets.

## Setup
- Models: <names and sizes>
- Languages: <which, how many>
- Data / benchmarks: <names>
- Baselines: <names>

## Key results
- <finding, with the number and what it is compared against> (Table 2)
- ... 2–5 bullets

## Limitations (stated by the paper)
- <limitation> (Sec. 7)

## Future work (stated by the paper)
- <direction> (Sec. 8)
```

Rules:
- 400–600 words, plain Markdown, no LaTeX.
- Every number carries where you read it (`Table 2`, `Sec. 5.1`, `Fig. 3`). If you cannot point to it, leave the number out.
- Limitations and future work only as the paper states them, each with where. If it states none, write `- none stated`: do not supply your own, because the open-problems section separates what papers say from what is inferred.
- Setup is what the experiments actually used. It is what lets the open-problems section see assumptions every paper shares (the same languages, the same model scale), so be complete.

## 3. Extract the main figure

The main figure is the one that explains what the paper does: for a method
paper the overview / architecture figure (usually Figure 1 or 2); for a
benchmark the figure showing how it is built or what a task looks like; for an
analysis paper the figure carrying the central finding. Not a teaser example or
a results plot if an overview figure exists.

```bash
$PY $FIG list "<pdf>"                                   # figures with page, caption, detected box
$PY $FIG crop "<pdf>" --figure N --out "<deck>/<image>"   # 600 DPI PNG
```

Then open the PNG with the Read tool and check it: every panel, label and legend
is in; the caption, body text and neighbouring figures are out. If the box is
wrong or the figure was listed with `"bbox": null`:

```bash
$PY $FIG preview "<pdf>" --page P --out /tmp/<key>_pP.png   # page with detected boxes drawn
$PY $FIG crop "<pdf>" --page P --bbox x0,y0,x1,y1 --out "<deck>/<image>"   # PDF points, top-left origin
```

Re-crop until it is right. If the paper has no figure at all, crop its main
results table (`--table N`) instead.

## 4. Write the slide

The Problem and Method bullets are a selection from the summary's sections of the
same name, shortened for the slide. Copy this frame and replace the content. Keep the structure, the commands and
the block titles exactly as they are. `\papermeta`, `\figcaption` and
`\paperbody` set the font sizes and spacing for every paper slide in the deck
(they are defined in `main.tex`); do not add size or `\vspace` commands of your own.

```latex
\begin{frame}{<Short name>: <what the paper does, in a few words>}
  \papermeta{<First author> et al., <Venue>, <Year> (arXiv:<id>)}
  \begin{columns}[T]
    \begin{column}{0.42\textwidth}
      \centering
      \includegraphics[width=\linewidth,height=42mm,keepaspectratio]{<image>}

      \vspace{1mm}
      \figcaption{Fig. N of the paper: <what the figure shows, one line>.}
    \end{column}
    \begin{column}{0.55\textwidth}
      \paperbody
      \begin{block}{Problem}
        \begin{itemize}\setlength{\itemsep}{0pt}
          \item ...
          \item ...
        \end{itemize}
      \end{block}
      \vspace{-2mm}
      \begin{block}{Method}
        \begin{itemize}\setlength{\itemsep}{0pt}
          \item ...
          \item ...
        \end{itemize}
      \end{block}
    \end{column}
  \end{columns}
\end{frame}
```

**The slide is small.** Beside the figure there is room for about nine lines of
bullet text in total, at about 50 characters a line. Text beyond that is pushed
off the bottom of the slide and is simply not shown — an over-full Problem block
makes the whole Method block disappear. So the limits below are hard limits, and
the deck's checker rejects a slide that breaks them:

- **Problem: 2 bullets. Method: 2 or 3 bullets.** Never more.
- **Each bullet at most 90 characters; all bullets together at most 380.** No nested lists.
- **Frame title at most 50 characters**, name and colon included; a longer title is cut off at the right edge.
- **Figure caption at most 90 characters.**

Fitting a paper into that space is the actual work. Choose the two things a
newcomer most needs to know about the problem and the two or three about the
method, and say each one plainly; leave the rest out rather than compress it into
fragments. If you find yourself wanting a fourth Method bullet, one of the four
is not essential.

- **Frame title** — the name people use for the paper (its method or benchmark name; otherwise 2–3 words for its idea), a colon, then what it does.
- **\papermeta** — first author's surname as printed in the PDF. If you were given no arXiv id but the PDF shows one, use it; if there is none, drop the `(arXiv:...)` part.
- **Problem** — what was broken, missing or unknown before this paper, and why existing approaches did not cover it. This is the gap, not the contribution.
- **Method** — how the paper addresses that gap: the core idea first, then the mechanism that makes it work. For a benchmark: what it contains and how it was built. For an analysis: what was measured and how. A headline result may take the last bullet if it is the point of the paper.
- **Describe the paper as it is.** The category is context, not a brief to argue: do not pick bullets or a figure to make the paper look like it belongs there. If it does not fit, the slide still says what the paper is about, and `category_fit` in the notes records the doubt.
- **Be specific**: what, how much, compared with what — not general praise. Numbers only if you read them in the paper, with what they refer to.
- **LaTeX**: escape `%`, `&`, `#`, `_` as `\%`, `\&`, `\#`, `\_`; put math in `$...$`; use ``` `` ''``` for quotes. The image path is relative to the deck root, exactly `<image>`.

Before finishing, count: bullets per block, characters per bullet, characters in
the title. Shorten until every limit holds.

## 5. Write the notes

`<deck>/<notes>` — plain text values (no LaTeX), read by the deck's scripts for
the overview slides:

```json
{
  "key": "<key>",
  "short_title": "the name used in the frame title, e.g. BMIKE-53",
  "focus": "what this paper focuses on, one line of at most 80 characters",
  "figure": "Figure 2, page 3, detected automatically | adjusted by hand",
  "category_fit": "ok | doubt: <why the paper seems to belong under another problem>",
  "unsure": "anything in the summary or on the slide you could not confirm in the PDF, or empty"
}
```

## 6. Report

Do not compile. Reply in a few lines: which figure you used and whether the box
needed adjusting, and anything you were unsure about.
