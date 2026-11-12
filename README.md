# Literature Review Pipeline

Claude Code skills that survey a research area you are new to: collect papers,
group them by the problem they address, download the PDFs, and build a Beamer
slide deck (landscape → one slide per paper → open problems).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and [Claude Code](https://claude.com/claude-code).
Clone once per research topic. Set the variables, then copy the rest as is:

```bash
AREA="multilingual knowledge editing"   # research area, as broad as you want it
YEARS="2023-"                           # publication years
MIN=30                                  # target number of papers (try 15 on a first run)
DIR=~/$(echo "$AREA" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed 's/-$//')-review

git clone https://github.com/mjkmain/literature-review-pipeline.git "$DIR"
cd "$DIR" && ./setup.sh   # .venv (PyMuPDF) + TinyTeX in ~/.TinyTeX; first run on a machine takes a few minutes, later ~1 s
```

## Usage

Run everything at once (no questions in between, one report at the end):

```bash
claude "/literature-review $AREA — years: $YEARS — min: $MIN"            # add " — korean" for slides-ko.pdf
```

Or start `claude` and run the steps one by one, checking each output. Slash
commands do not expand shell variables, so type the area itself here.
The skills run only when invoked.

```
/literature-collector <research area> — years: 2023- — min: 30   # → reference/papers.md
/literature-categorizer                                          # → reference/index.md
/paper-index-downloader                                          # → reference/<category>/*.pdf
/literature-slide-writer                                         # → slide/<area>-literature/slides-en.pdf
/literature-slide-writer — korean                                # optional: slides-ko.pdf
```

Step 4 runs one agent per paper, about 60k tokens each.

Rebuild a deck after editing it by hand:

```bash
cd slide/<area>-literature && make en     # or: make ko
```

## Layout

```
.claude/skills/                  # literature-review (runs all steps), one skill per step, paper-figure-extractor
slide/literature_review_template # Beamer template, copied for each deck
reference/                       # papers.md, index.md, downloaded PDFs (PDFs are git-ignored)
setup.sh, requirements.txt
```
