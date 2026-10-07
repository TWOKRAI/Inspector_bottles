---
name: project-haiku-classifier-failed-memory-tagging
description: "Haiku as a narrow classifier failed memory tagging (agreement with Sonnet 72 % mechanism / 69 % module, 174 errors on 367) — check agreement on a sample before trusting a cheap model / Haiku не справился с разметкой памяти, сверка с Sonnet на выборке до доверия дешёвой модели"
module: []
mechanism: [agents, measurement]
metadata:
  type: project
---

Atlas 2.4g.3, 2026-10-06. The owner's idea "Haiku instead of a local model" for repetitive work was tested on
tagging 367 memory lessons with the `memory-classifier` agent (`model: haiku`, `omitClaudeMd: true`, `tools: Read`,
vocabularies in the prompt, 7 slices of ≤ 200 KB).

Measured: Haiku returned 362/367 rows with 174 errors (134 descriptions without both RU and EN keywords, 33 tags
outside the vocabulary, 5 rows without a mechanism). Against Sonnet on a 30-file sample (seed 2024; a match = the
first mechanism of each side is in the other's set, modules intersect or both empty): mechanism 72 %, module 69 %,
threshold 80 %. Sonnet on all slices: 367/367, 0 errors; a reviewer's semantic sample of 20 found 0 wrong.

**Why:** vocabulary-constrained classification with "not X — use Y" definitions needs judgment Haiku did not show;
mechanical validation (vocab, language, coverage) catches format errors but not wrong-but-valid tags — only the
agreement sample does.

**How to apply:** before handing a batch job to Haiku, run it and Sonnet on a fixed random sample of ~30 and compare
with a pre-declared metric and threshold; below the threshold → Sonnet for the whole batch. Keep the mechanical
validator anyway (`collect.py`-style: vocab, language, coverage per row).
