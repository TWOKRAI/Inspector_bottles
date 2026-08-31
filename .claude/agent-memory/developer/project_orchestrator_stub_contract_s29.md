---
name: project-orchestrator-stub-contract-s29
description: S-29 closed — 4 new name-contract guards added for the remaining orchestrator-stub duplicates via a shared helper; test_hot_rebuild_provenance_hazards.py deliberately left untouched
metadata:
  type: project
---

S-29 (`plans/QUEUE.md`) asked to extend the S-26 guard
(`test_hot_rebuild_provenance_hazards.py::
test_the_stub_orchestrator_speaks_the_real_class_surface`) — which catches a
production rename of any name `configure_topology_engine`
(`multiprocess_prototype/backend/orchestrator_hooks.py`) reads off its
`orchestrator` argument — to the other 4 duplicate-orchestrator-stub test
files. Done via a shared helper,
`multiprocess_prototype/backend/tests/_orchestrator_stub_contract.py`
(`ORCHESTRATOR_SURFACE_THE_HOOK_USES` tuple +
`assert_stub_speaks_the_real_class_surface()`), called from one new test in
each of `test_hot_rebuild_parity_acceptance.py`,
`test_hot_rebuild_parity_hazards.py`, `test_orchestrator_hooks.py`,
`test_presentation_overlay_on_hot_swap.py`.

**Why `test_hot_rebuild_provenance_hazards.py` was left untouched** (its own
inline copy of the same 10-name tuple + check, NOT switched to import the
shared helper): the task scoped this explicitly as "already protected, extend
to the other four" — refactoring the one that already worked would be
unrequested adjacent-code cleanup, and touching it risks the exact kind of
diff-scope creep the project's developer rules forbid. Net effect: the
10-name surface tuple now exists in TWO places (the original in
`test_hot_rebuild_provenance_hazards.py`, the canonical one going forward in
`_orchestrator_stub_contract.py`) — a known, named, deliberate trade-off, not
an oversight. If a 6th orchestrator-stub duplicate ever appears, or if
`provenance_hazards.py` needs touching for an unrelated reason, that's the
natural point to fold its copy into the shared helper too.

**Why:** avoids exceeding task scope while still eliminating the duplication
class that S-29 exists to close for the 4 files actually in scope.

**Baseline discrepancy (not acted on, just recorded):** the queue text stated
"69 green tests" as the catalog baseline; the actual measured baseline
(2026-08-18, before any change) was **70** (`collected 70 items`,
`70 passed`). Did not investigate the 1-test gap — out of scope, and the
task's acceptance criterion was relative ("69 plus what you add"), so the
discrepancy doesn't block anything. Worth a fresh count if a future task cites
"69" as this catalog's baseline.

See [[feedback_rename_injection_substring_trap]] for the break-injection
methodology finding from the same task's verification pass.

**Update 2026-08-18 (review-fix task, `telemetry-stage6` branch): the duplicate
WAS folded in — the "natural point" predicted above arrived.** A synchronous
review (verdict 6/10) on an unrelated ADR-PM-039 change flagged the SAME guard
for a deeper defect (see [[feedback_rename_injection_substring_trap]]'s
addendum: the word-boundary regex closed the prefix-substring trap but not the
sibling comment-text trap — a comment mentioning the old name as text still
faked a pass). Fixing that required touching
`assert_stub_speaks_the_real_class_surface()` anyway, so
`test_hot_rebuild_provenance_hazards.py`'s inline copy was folded into the
shared helper in the SAME task (its own test function now just calls
`assert_stub_speaks_the_real_class_surface(_StubOrchestrator)`, docstring kept
verbatim — only the body was duplicate). The 10-name tuple now truly lives in
ONE place only. Proven with the SAME paired-injection methodology this file's
sibling memory describes, run twice — once against the OLD regex version (A:
rename 10 sites -> 5/38 red; B: rename + 1 comment -> false 38/38 green) and
once against the NEW AST version (A -> 5/38 red; B -> 5/38 red, HELD) — on the
3 real production files (`orchestrator.py`, `process_manager_process.py`,
`process_module.py`), backed up and restored via `cp`/md5 (not git) since
other uncommitted work was live in the same tree. Both full gates green after:
process_module 2302/2302, prototype-backend 74/74.
