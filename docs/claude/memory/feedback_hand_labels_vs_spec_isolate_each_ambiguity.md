---
name: hand-labels-vs-spec-isolate-each-ambiguity
description: "when hand labels and the written spec disagree or the label is silent, give each ambiguous item its own named test so the lead flips one literal; a label's explanatory note can be factually wrong / ручные метки против спеки, фикстура на реальных данных, слепой тестер"
module: [scripts]
mechanism: [acceptance, fixtures]
role: tester
metadata:
  type: feedback
---

Task 2.3 of `commit-mechanism` (classifier fixture, 19 hand labels + spec DESIGN (a)-(i)). Reading the
real transcripts against the labels showed four places where the two lead-owned artifacts disagree:
`hidden` for items 6/10/19 (label silent, rule (h) says hidden — same shape as item 16 which the label
marks hidden), writer split of item 4 (label "undecided because an earlier A1 retry"; the transcript has
no earlier A1 retry, the files were `cp`-ed by a Bash loop), outcome of quiet `-q` commits 14/15 (label
"success", rule (e) cannot produce success without a `[branch sha]` line), `any_failure` unit.

**Rule:** do not average the two sources and do not silently pick. Put each ambiguous item in its OWN
parametrized test (or its own single test) with a docstring that names both readings; keep the main
table/loop tests on the unambiguous items. The lead then flips one literal per decision instead of
re-reading a 100-test failure list. State the pick and the other reading in the report.

**Also:** a label's explanatory note is an opinion, check it against the transcript (the "earlier A1 retry"
was not there). And a real-data fixture gives free discriminators — here item 10/16 pass the scratchpad
path `.../Local/Temp/...` only inside `-F <path>`, which punishes an implementation that scans the whole
command for `/temp/` instead of the cd/cwd target.

**Why:** a failure list from one merged test hides which decision is open; one named test per ambiguity turns each decision into one flipped literal.
**How to apply:** blind tester + labelled fixture + spec that is a design, not an `interface.py`. Also see
[[feedback_red_without_interface_needs_one_named_guessed_hook]] (the `--json` shape was a guess kept in
three accessor functions).
