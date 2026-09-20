---
name: feedback-ratio-criterion-bounded-by-out-of-scope-code
description: Before chasing a cost-RATIO acceptance criterion between two code paths, check whether the task's file scope only covers one side of the ratio — a zero-cost fix on that side may still not reach the target.
metadata:
  type: feedback
---

When an acceptance criterion is phrased as a RATIO between two costs (e.g. "disabled
path ≤ 10% of enabled path"), and the task's `Files:` scope only lets you touch ONE
side of that ratio, compute the theoretical floor BEFORE attempting further
optimization: if `owned_cost → 0` still doesn't push the ratio under target because the
OTHER side's cost (outside scope) already sets the ceiling, the criterion cannot be
closed from within this task — full stop, no amount of extra cleverness in the owned
file fixes it.

**Why:** Task 2.4 (`observability-closure`, Ф2) asked for "500 disabled leaves ≤ 10% of
500 enabled leaves" cost, with `Files:` scoped to `observation_policy.py` +
`telemetry.py` only (NOT `numbers_gate.py` / `stats_manager.py` /
`observation_manager.py`, which own the downstream cost of an ENABLED leaf — tap
dispatch, aggregation). After adding a per-path memoization cache, the raw
`ObservationPolicy.resolve()` cost dropped ~100x (11.87us → ~0.10us, warm), but the
measured end-to-end ratio (disabled/enabled via `StatsManager.record_metric()`) was
14.4–15.4%, not ≤10%. Math check: disabled cost = ~0.10us (resolve) + ~0.40us (call-chain
overhead in files outside scope); even resolve()→0 only drops disabled from ~0.50us to
~0.40us, and 0.40/3.4 ≈ 11.8% — STILL above the 10% target. The gap is structural, not a
missed optimization, and closing it needs a task whose `Files:` scope includes the
downstream module.

**How to apply:** When a spec hands you a ratio criterion, before writing code: (1)
identify which module/file owns each side of the ratio, (2) if your `Files:` scope only
covers the numerator (or denominator), do a quick back-of-envelope "what if my side were
free" calculation using early measurements, (3) if the target is still unreachable even
at zero cost on your side, say so explicitly in the report with the arithmetic — don't
silently ship "close but not met" as if more polish would close it, and don't expand
scope to touch out-of-scope files without asking first. This is a report-honestly
situation, not a keep-optimizing situation.
