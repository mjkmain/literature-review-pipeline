#!/usr/bin/env bash
# One-time environment setup for the literature-review pipeline.
#
#   ./setup.sh
#
# 1. Python: creates .venv with uv and installs requirements.txt (PyMuPDF, Pillow).
#    The skills' scripts run with .venv/bin/python.
# 2. LaTeX: installs TinyTeX into ~/.TinyTeX (no admin rights needed) unless
#    xelatex and latexmk are already available, then adds the packages the
#    slide template needs. `make` in a slide directory then builds the PDF.
#
# Safe to run again: finished steps are skipped.
set -euo pipefail
cd "$(dirname "$0")"

# ---------------------------------------------------------------- Python
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
[ -d .venv ] || uv venv .venv
uv pip install --quiet --python .venv/bin/python -r requirements.txt
echo "Python: $(.venv/bin/python --version), PyMuPDF $(.venv/bin/python -c 'import pymupdf; print(pymupdf.__version__)')"

# ---------------------------------------------------------------- LaTeX
tinytex_bin() { ls -d "$HOME"/.TinyTeX/bin/*/ 2>/dev/null | head -n 1; }

if ! command -v xelatex >/dev/null 2>&1 || ! command -v latexmk >/dev/null 2>&1; then
  if [ -z "$(tinytex_bin)" ]; then
    echo "Installing TinyTeX into ~/.TinyTeX ..."
    curl -fsSL "https://yihui.org/tinytex/install-bin-unix.sh" | sh
  fi
  export PATH="$(tinytex_bin):$PATH"
fi

if command -v tlmgr >/dev/null 2>&1; then
  # What the slide template (beamer + pptblue theme, XeLaTeX, Korean) needs.
  # (unfonts-core is left out on purpose: it is a very large download and only a
  #  last-resort fallback; the template ships its own Gmarket Sans fonts.)
  timeout 900 tlmgr install latexmk xetex beamer translator pgf xcolor fontspec booktabs colortbl tools \
    kotex-utf xetexko kotex-plain cjk-ko etoolbox amsmath amsfonts hyperref geometry \
    >/dev/null || echo "tlmgr did not finish; run ./setup.sh again, or 'tlmgr install <package>' for anything missing" >&2
fi

echo "LaTeX: $(xelatex --version | head -n 1)"
echo "latexmk: $(latexmk --version | grep -i version | head -n 1)"
case ":$PATH:" in
  *":$(tinytex_bin 2>/dev/null):"*) ;;
  *) [ -n "$(tinytex_bin)" ] && echo "Note: add $(tinytex_bin) to your PATH if xelatex is not found in a new shell." ;;
esac
echo "Setup complete."
