---
name: review-file-names-need-plan-prefix
description: docs/reviews/<date>_task-X.Y-* collides across parallel plans — prefix review/report files with the plan (gui-, lifecycle-)
metadata:
  type: feedback
---

Several plans run in parallel with the same task numbers (gui-service 1.2 vs lifecycle-stop-ownership 1.2/1.3), and
`docs/reviews/2026-09-24_task-1.2-*` / `task-1.3-review.md` were already taken by lifecycle when gui-service wrote its
reports. Name reports `<date>_<plan-prefix>-<task>-<role>.md`, e.g. `2026-09-24_gui-1.3-design.md`,
`2026-09-24_lifecycle-task-1.2-tester.md`.

**Why:** a same-named file from another plan is overwritten on merge or silently read as this task's evidence.
**How to apply:** before writing to docs/reviews/, `ls docs/reviews/<date>_*` and use the plan prefix; tell subagents the
exact filename. Related: [[a-new-plan-must-be-placed-among-its-neighbours]].
