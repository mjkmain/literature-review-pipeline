# Render the slides to PDF with XeLaTeX.
#
#   make        English version  -> <area>_slide_en.pdf
#   make ko     Korean version   -> <area>_slide_ko.pdf
#
# <area> is this directory's name without "-literature"
# (slide/tokenizers-literature -> tokenizers_slide_en.pdf); override with `make AREA=name`.
#   make all    both
#   make clean  remove build/ (intermediate files); keeps the PDFs
#   make distclean  remove build/ and the PDFs
#
# Intermediate files (.aux, .log, ...) go to build/. latexmk only recompiles
# what changed, so re-running is cheap.

AREA ?= $(patsubst %-literature,%,$(notdir $(CURDIR)))
LATEXMK := latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=build

.PHONY: en ko all clean distclean

en:
	$(LATEXMK) -jobname=slides-en main.tex
	cp build/slides-en.pdf $(AREA)_slide_en.pdf

# \buildkorean makes main.tex switch to sections-ko/ (same as uncommenting \renderkorean).
ko:
	$(LATEXMK) -jobname=slides-ko -usepretex='\def\buildkorean{}' main.tex
	cp build/slides-ko.pdf $(AREA)_slide_ko.pdf

all: en ko

clean:
	rm -rf build

distclean: clean
	rm -f $(AREA)_slide_en.pdf $(AREA)_slide_ko.pdf
