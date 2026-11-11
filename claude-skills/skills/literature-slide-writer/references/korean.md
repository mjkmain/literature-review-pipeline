# Korean version

Read this only when the user asked for Korean slides. It produces
`sections-ko/` and `slides-ko.pdf` from the finished English deck. The English
deck must already pass `deck.py check`: translate final text, not drafts.

The Korean deck is for a Korean-speaking researcher who reads English papers
daily. They want the explanation in Korean and the vocabulary of the field left
as they will meet it in the papers. A slide where every term has been turned
into Korean is harder for them to read, not easier.

## What stays in English

- Section, subsection and **category names**, exactly as in the English deck.
- Paper titles, short titles, author names, venues.
- Names of methods, models, datasets, benchmarks, metrics.
- Block titles: `Problem`, `Method`, `What remains unsolved`, `Why current approaches fall short`, `Evidence`, and the labels `Stated by papers` / `Inferred from the landscape`.
- **Technical terms** without a settled Korean equivalent, or whose translation reads awkwardly: fine-tuning, in-context learning, cross-lingual transfer, steering vector, sparse autoencoder, attention head, benchmark, prompt, token, embedding, hallucination, ... Do not coin translations. A term a Korean researcher would say in English in conversation stays in English.

## What becomes Korean

The explanatory text: frame-title summaries after the colon, bullets, figure
captions, problem-focus texts, one-line paper descriptions.

- Write concise note style (개조식): end bullets with a noun or noun-form ending (`~함`, `~임`, `~필요`, `~한계`), not full sentences ending in `~다` or `~습니다`.
- Translate the meaning, not the sentence structure. Re-read each bullet as Korean: if it reads like a translation, rewrite it the way a Korean researcher would put it on their own slide.
- Mixed text is normal: `기존 knowledge editing 방법은 편집한 언어 밖에서는 효과가 유지되지 않음`.
- Korean characters are wider than Latin ones, so the limits are lower than in English: paper-slide bullets at most 55 characters (230 in total per slide), frame titles at most 32, open-problem bullets at most 60. The checker enforces these with `--lang ko`.
- Numbers, math, figures, and the slide structure are identical to the English version. Do not add, drop or reorder content.

## Steps

1. **Paper frames.** For each English `sections/papers/<category>/<key>.tex`, write `sections-ko/papers/<category>/<key>.tex`: the same frame with the text translated under the rules above. The `\includegraphics` path is unchanged (figures are shared). Use agents for this, one per category, each given this file and the list of frames to translate; each writes only under `sections-ko/papers/<its category>/`.
2. **Paper section.** `deck.py assemble <deck> --lang ko` writes `sections-ko/paper_summaries.tex`.
3. **Overview.** Copy `sections/overview.tex` to `sections-ko/overview.tex` and translate the problem-focus texts and the one-line paper descriptions. Keep `\section{Overview}`, the frame titles (category names), the short titles and the venues as they are.
4. **Open problems and title.** Translate `sections/open_problems.tex` and `sections/title.tex` into `sections-ko/` the same way. The frame title of an open problem is explanatory text, so it is translated.
5. **Build and check.** `deck.py check <deck> --lang ko`, fix what it reports, then `deck.py sheets <deck> --lang ko --out <deck>/build/sheets-ko-1` and read the sheets: Korean line breaks and overflow differ from the English deck.
