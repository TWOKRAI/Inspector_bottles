---
name: stand-lock-check-must-gate-the-command
description: A subagent that "checks stand.lock" must gate the test command on it (`[ ! -e lock ] && pytest`), not just print it in the same command — otherwise it runs into a neighbour's measure
metadata:
  type: feedback
---

2026-09-30: the reviewer was told "before every pytest run check stand.lock". It did — `cat stand.lock; pytest …` in one
command — and pytest ran anyway: the neighbour's `measure` lock had appeared seconds earlier, ~5.7 s of Qt tests landed
in the neighbour's A/B window, and the neighbour had to be told to re-measure.

**Why:** a check whose result nothing reads is not a gate. Agents batch the check and the action into one shell call.

**How to apply:** in every brief that runs tests while a neighbour may measure, give the literal guarded form:
`[ ! -e /d/PROJECT_INNOTECH/Inspector_vision/stand.lock ] && <pytest …> || echo "STAND LOCKED — skipped"`.
Same for my own runs. If a neighbour announced a measure "in N minutes", finish or pause test work before N.
Protocol: [[shared-stand-and-tests-protocol]].
