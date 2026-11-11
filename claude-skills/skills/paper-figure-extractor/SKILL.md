---
name: paper-figure-extractor
description: "Extracts a figure (or table) from a research paper PDF as a high-resolution image. The figure's region is computed from the PDF's own layout data with PyMuPDF — caption position plus the drawings, images and labels around it — and cropped at 600 DPI, optionally also as a vector PDF. Used by the slide step of the literature-review pipeline and usable on its own."
disable-model-invocation: true
argument-hint: "<paper.pdf> [figure number] [output path]"
---

# Paper Figure Extractor

Figures in papers are mostly vector drawings, so they cannot be pulled out as
embedded image files, and a region picked by eye from a rendered page is slow to
get right. The bundled script reads the page's layout data instead: it finds
the caption ("Figure 2:") in the text layer and takes the union of the drawings,
images and labels that belong to it. The crop is then rendered straight from
the PDF, so it is as sharp as the source at any resolution.

The detection is right most of the time, not always. So the rule of this skill
is: **look at every crop before using it.** A figure with a missing panel on a
slide is worse than no figure, and only an eye catches it.

Request: $ARGUMENTS

## Setup

The script needs PyMuPDF, installed in the project's virtual environment by
`./setup.sh` in the repository root. Run it with that interpreter:

```bash
PY=<repo-root>/.venv/bin/python
FIG=<this-skill-dir>/scripts/extract_figure.py
```

If `.venv` is missing, run `./setup.sh` first.

## Workflow

### 1. List the figures

```bash
$PY $FIG list paper.pdf            # add --tables to include tables
```

Each item has the figure `number`, `page`, `caption`, the detected `bbox`
(PDF points, origin at the top-left of the page), `width_fraction` (how much of
the page width it spans) and a `note`. An item with `"bbox": null` has a caption
but no graphics could be tied to it — typical for figures made only of text,
such as prompt templates; handle those with a manual box (step 4).

### 2. Choose the figure

If the request names a figure, take that one. If it asks for the paper's *main*
figure, choose the one that explains what the paper does, by reading the captions
(and the paper, if needed):

- a method paper → the overview / architecture / pipeline figure, usually Figure 1 or 2;
- a benchmark or dataset paper → the figure showing how the benchmark is built or what a task looks like;
- an analysis paper → the figure carrying its central finding.

Prefer these over teaser examples and result plots, and ignore appendix
figures. If the paper has no usable figure at all, take its main results table
(`--table N`).

### 3. Crop and look

```bash
$PY $FIG crop paper.pdf --figure 2 --out figures/paper_fig2.png
```

The result reports the box, the DPI used (600 unless the image would exceed
9000 px on its longest side) and the pixel size. Add `--vector` to also write
`paper_fig2.pdf`, a vector crop that stays sharp at any size and that LaTeX can
include directly.

Then open the PNG with the Read tool and check:

- the whole figure is there — every panel, axis label, legend, and sub-caption like "(a)";
- nothing else is — no main caption, no body text, no neighbouring figure or table;
- it is the figure the caption describes.

If it is right, the job is done.

### 4. Fix a wrong or missing box

Render the page with the detected boxes drawn on it:

```bash
$PY $FIG preview paper.pdf --page 4 --out /tmp/page4.png
```

The output gives `page_size_pt` (for example 612 × 792) and the boxes. Read the
image, work out the correct box in the same point coordinates — take the
detected box as the starting point and move the edge that is off — and crop it:

```bash
$PY $FIG crop paper.pdf --page 4 --bbox 104,79,508,340 --out figures/paper_fig2.png
```

Look at the result again and adjust until it passes the check in step 3. Two or
three rounds are normal for an unusual layout; if a figure still cannot be
isolated, say so rather than hand over a bad crop.

## Report

State which figure was extracted and where it is, so the caller can cite it:

```
Figure 2 (page 4) → figures/paper_fig2.png, 3360 × 2170 px at 600 DPI
Caption: "Overview of AnomalyCLIP. ..."
Box: detected automatically | adjusted by hand (reason)
```
