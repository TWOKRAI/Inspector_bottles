---
name: road-lenses-what-each-sees
description: Measured (2026-09-03, CPython 3.12.12) blind spots of the perf-bench lenses in modules/tests/_road_cost.py — count_calls vs tracemalloc peak vs sys.monitoring INSTRUCTION; which one coverage inflates and which not
metadata:
  type: project
---

For "did this road do extra work" gates, `sys.monitoring` INSTRUCTION count is the lens that
sees every construction form and that coverage does not move; `count_calls` (setprofile) is
blind to type constructors; `tracemalloc` peak depends on the coverage CORE, not only on the
coverage version.

**Why (all numbers run, not reasoned):**
- micro: `dict(d)`, `{**d}`, `{'a':1}`, `list(d)`, `object()`, `str()` all give `count_calls == (1,1)`
  — same as `lambda: None`; `sys.monitoring` CALL sees `dict(d)` but not `{**d}`/literals;
  INSTRUCTION sees all (11 → 13..17).
- stand (Task 2.10 bench): E1 (record assembled before `gate.allow`) → INSTRUCTION 139→150 on
  the disabled road, identical under no-cov / CTracer / sysmon / pytrace; `tracemalloc` peak
  ratio tree/E1 = 0.367/0.738 no-cov, 0.417/0.504 CTracer, 0.367 sysmon, **0.440 pytrace**
  (ceiling 0.46) — `COVERAGE_CORE` flips it silently.
- ratio-of-peaks gate loosens from the denominator: E1 + ~600 B transient work on the enabled
  road → 0.479 → one more list and E1 passes green.
- `peak_alloc` first call for a fn differs from later ones when the road has had only ~100
  prior calls (335 vs 363, 2470 vs 990); in the bench 200k `timed_pair` calls precede it, so
  solo and in-suite (2831 tests) values were byte-identical.
- 3-window/gc-on `_timed_pair` copies (logger bench, source stamping) vs 5-window/gc-off: all
  within each other's spread at 6.7x / 2x margins — hygiene debt, not a measurement gap.

**How to apply:** when a bench must prove "no extra work on a road", gate on an
INSTRUCTION-count literal pair (warm-up first: cold call is 765 vs 139; filter by thread;
pick a free tool id), report tracemalloc peak, never threshold it across coverage modes.
Related: [[injection-must-use-a-different-lens-than-the-test]].
