# Render the slides to PDF with XeLaTeX.
#
#   make        English version  -> slides-en.pdf
#   make ko     Korean version   -> slides-ko.pdf
#   make all    both
#   make clean  remove build/ (intermediate files); keeps the PDFs
#   make distclean  remove build/ and the PDFs
#
# Intermediate files (.aux, .log, ...) go to build/. latexmk only recompiles
# what changed, so re-running is cheap.

LATEXMK := latexmk -xelatex -interaction=nonstopmode -halt-on-error -outdir=build

.PHONY: en ko all clean distclean

en:
	$(LATEXMK) -jobname=slides-en main.tex
	cp build/slides-en.pdf slides-en.pdf

# \buildkorean makes main.tex switch to sections-ko/ (same as uncommenting \renderkorean).
ko:
	$(LATEXMK) -jobname=slides-ko -usepretex='\def\buildkorean{}' main.tex
	cp build/slides-ko.pdf slides-ko.pdf

all: en ko

clean:
	rm -rf build

distclean: clean
	rm -f slides-en.pdf slides-ko.pdf
