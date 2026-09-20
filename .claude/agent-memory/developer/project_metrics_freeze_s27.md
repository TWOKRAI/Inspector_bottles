---
name: metrics-freeze-s27
description: S-27 (Task 5.4, Ф5 observation-port) — MetricsCollector frozen with ceiling+voice; what's proven and what isn't (the TOCTOU test caveat)
metadata:
  type: project
---

`multiprocess_framework/modules/data_schema_module/core/metrics.py`
(`MetricsCollector`) was frozen 2026-08-26 per owner's contract (ADR-DS-009):
`TIMINGS_CEILING = 1000` per key, new records dropped past ceiling (not old
ones), drop count named via `get_metrics()["timings"][key]["dropped"]`, a
one-time WARNING via `get_std_logger` containing the literal substring
"никто не читает", and `record_metric` changed from overwrite to
counter-additive semantics. Verified before the change: zero production
sites and zero existing repo tests call `record_metric` directly — all 14
production sites (`model_factory.py` ×8, `schema_registry.py` ×6) go through
`record_timing`/`increment_metric` only, so the semantic change was safe.

**Why:** owner-assigned contract, Task 5.1's inventory found 14 live callers
but zero readers of `get_metrics()`/`reset()` — an unbounded silent
accumulator that the project's "FREEZE, not KILL" rule forbids deleting.

**How to apply:** if touching this file again, read ADR-DS-009 in the
module's `DECISIONS.md` first — it has the full rationale including the
rejected alternatives (drop-oldest instead of drop-newest, eager vs lazy
logger import).

**Honest gap worth knowing:** the concurrent-voice hazard test
(`test_voice_sounds_exactly_once_under_concurrent_first_calls` in
`test_metrics_freeze_hazards.py`) could NOT be proven via break-injection
under normal thread contention — removing the `RLock` around the
check-then-set flag and running 8-16 threads via `sys.setswitchinterval`
tuning still didn't reliably reproduce the duplicate-voice race; it only
went red once an artificial `time.sleep()` was inserted between the read and
the write inside the broken code. The TOCTOU window there is two adjacent
bytecodes and CPython's GIL essentially never interleaves at that
granularity under black-box scheduling. The lock is correct by
construction/code-review, not by this test's proof. See
[[feedback_lazy_import_for_layer0_data_schema_files]] for the other
non-obvious finding from this task (the circular-import trap on
`get_std_logger`).
