---
name: a-cross-track-dependency-can-name-the-wrong-plane
description: Before pricing a cut, check which PLANE the named mechanism lives on — otel plan said "v2 needs closure 3.4 declare_metric(unit)" but declare_metric is the levels catalog, not the numbers plane where NumberRecord.unit already sits
metadata:
  type: feedback
---

Rule: when a plan names a dependency as "<task> via <function signature>", reproduce which plane
that function feeds (its consumers), not just that the function exists.

**Why:** 2026-09-07, Ф3 cut of `observability-closure`. Both the lead and the otel plan priced
Task 3.4 as "the entry for OTLP metrics" because the card said `declare_metric(name, *, owner,
unit, description, kind)`. Running it: `declare_metric` feeds `gated_metrics()` → publisher-gate,
`introspect.telemetry.gated_metrics`, GUI rows — the state-tree LEVELS plane. Numbers go through
`record_metric/gauge/record_timing` → `NumberRecord`, which already had `kind` and an inert
`unit=""` slot. `PluginContext.declare_metric` even refuses dotted names, so no stats-plane name
could ever be declared there. The dependency was right in intent and wrong in address; a "shrunk"
3.4 would have glued two planes by bare name (first-wins-silent catalog, empty-axis guard).

**How to apply:** for any "X depends on Y's signature" claim, list Y's consumers by grep and run one
call through Y; if the consumers are on another plane than X's data, the dependency is misaddressed
and the fix is a re-home + ADR line, not a smaller version of the task.
