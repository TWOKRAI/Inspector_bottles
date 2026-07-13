---
name: feedback-verify-heuristic-fix-against-golden-recipes
description: Before "fixing" a documented join/inference heuristic in blueprint.py, run the full prototype suite (characterization + golden recipes) — an audit-flagged "bug" may be an accepted, load-bearing trade-off.
metadata:
  type: feedback
---

When a follow-up audit flags a heuristic in `SystemBlueprint.infer_missing_inspectors`
(topology join-inference in `process_manager_module/topology/blueprint.py`) as
"losing information" (e.g. AU-3: a source with two different data_type tags only
contributes one tag to `inputs`), do not assume the heuristic is simply broken and
"fix" it by making the grouping more granular (e.g. group by target-port instead of
by source-process) without first running the full test suite, especially
`multiprocess_prototype/backend/tests/test_build_characterization.py` (golden-snapshot
per real recipe) and `multiprocess_prototype/backend/topology/tests/test_join_inspector_from_wires.py`.

**Why:** attempted a "take all tags per source" fix for AU-3 (follow-up audit В1,
2026-07-12) grouped by (source, target_port) instead of by source alone. It passed a
synthetic unit test but broke the real `hikvision_letter_robot.yaml` recipe:
`circle_detector` emits ONE item with fields `frame`+`detections`, wired to two
DIFFERENT target ports (`circle_draw.frame`, `circle_draw.detections`) — structurally
identical, from the wires graph alone, to "one source genuinely emitting two
independent data_type streams". The existing single-tag-per-source heuristic is a
deliberate, already-documented trade-off (ADR-PMM-017 known edges), not an oversight —
the correct call was to document it as edge п.5 with a regression test proving the
current collapse behavior, not to change runtime behavior.

**How to apply:** for any change to `infer_missing_inspectors` or similar
topology-inference heuristics, run `pytest multiprocess_prototype -q` (or at minimum
the characterization + join-inspector test files) BEFORE concluding the change is
correct — a synthetic framework-level unit test passing is not sufficient evidence.
If a real recipe's golden snapshot changes, that is a strong signal to document the
edge in ADR-PMM-017 (pattern: append a new numbered point, minimal diff) rather than
alter behavior, since the escape-hatch (`inspector: {mode: ..., inputs: [...]}`)
already exists for recipes that need different semantics.
