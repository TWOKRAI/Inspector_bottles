---
name: sequencing-observability-then-audit
description: Owner decision 2026-09-02 — finish the observability system first (observability-closure), then run ponytail-audit over the whole framework; do not audit mid-phase
metadata:
  type: project
---

Owner's sequencing decision (2026-09-02): finish the observability system first, then run
`ponytail-audit` over the framework. Review Ф2 measured the weight (212k code lines non-test,
prose 55-63% in core observability files, four god files 1.5k-4k lines, 64 schema fields in
9 sub-sections) and recommended subtraction; the owner chose to complete the mechanism before
cutting.

**Why:** auditing a moving subsystem gives findings that expire with the next task; auditing
once at a stable point gives one ranked list.

**How to apply:** "finish" means Ф2 + Task 2.9 + merge to main, then Ф3–Ф5 of
`observability-closure` in consolidation mode (no new planes without a named consumer, see
[[knobs-universal-manager]]). Run `ponytail-audit` at two points: a scoped pass over the
observability subsystem right after the Ф2 merge (cheap, catches prose and god files while the
context is fresh), and the full-framework pass after Ф5. Do not propose the audit mid-phase.
Related: [[project-priority-engine-first]], [[feedback-freeze-over-kill]].
