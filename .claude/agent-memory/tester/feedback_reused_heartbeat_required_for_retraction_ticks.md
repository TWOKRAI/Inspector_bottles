---
name: reused-heartbeat-required-for-retraction-ticks
description: A multi-tick ProcessHeartbeat scenario (plugin-level retraction, gate due_metrics) must reuse ONE ProcessHeartbeat instance across ticks — a fresh instance per tick silently resets per-instance bookkeeping and produces a false negative
metadata:
  type: feedback
---

When black-box-driving `ProcessHeartbeat._publish_telemetry_to_tree` /
`_build_telemetry_gate` across several simulated ticks (via a fake `clock`
callable), constructing a **new** `ProcessHeartbeat(svc, clock=...)` for every
tick — instead of mutating a shared `clock["t"]` dict and calling the SAME `hb`
object repeatedly — silently discards whatever per-instance state the collector
uses to detect "this plugin-level name used to be published and just
disappeared, emit a retraction (`None`) for it". Confirmed empirically
(`telemetry-stage6`, S-31/quartet acceptance, 2026-08-19): a scenario where a
plugin declares+publishes a level, then `_do_shutdown()`s (→
`PluginLevels.retract(owner)`, confirmed via `store.publications()` going
empty and `store.pending_retractions()` gaining the name) —

- with a **fresh `ProcessHeartbeat` per tick**: the retraction NEVER reaches
  the tree across 3+ ticks (looks like a real defect — "снятие не доезжает"),
- with the **same `hb` reused** (`hb = ProcessHeartbeat(svc, clock=lambda:
  clock["t"])` built once, `clock["t"]` mutated between ticks): the
  retraction reaches the tree as `None` on the very next tick.

**Why:** this was a genuine methodology bug in my own probing harness, not a
production defect — caught only by deliberately re-running the same scenario
both ways and comparing. Without the comparison it would have shipped as a
false RED for a task's Д3-equivalent criterion.

**How to apply:** in any multi-tick `ProcessHeartbeat` acceptance/hazard test
in `process_module`, build `hb` ONCE outside the tick loop and drive time via
a mutable clock closure — never re-instantiate per tick. If a scenario
requires isolating ticks (e.g. comparing "fresh boot" behavior), say so
explicitly and treat the fresh-instance variant as a DIFFERENT, deliberately
named scenario, not a drop-in replacement for the reused-instance one.
See also [[feedback_do_shutdown_on_unbooted_plugin_is_a_silent_noop]] for the
sibling trap in the same exploration (plugin lifecycle, not heartbeat
instance identity).
