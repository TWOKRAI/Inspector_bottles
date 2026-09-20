---
name: emergency-log-is-stderr-only
description: emergency_log lands only in stderr (lastResort); FallbackLogger buffers before LoggerManager and drains into the file — verdict on 2.12 (2026-09-03) ruled the view is the right address for config-validator voices
metadata:
  type: project
---

Verdict 2026-09-03 (Task 2.12, observability-closure): a config validator's operator-facing
voice (ADR-PM-046, `stats.enabled` repurposed) went through `_fallback.emergency_log`,
which writes to stdlib directly; stdlib root has no handlers in framework processes, so the
voice reaches `logging.lastResort` (stderr) and 0 lines in `logs/`. Measured with a real
`LoggerManager` + file channel: `FallbackLogger(name).warning()` before the manager is
buffered (`early_buffer_stats.pending`) and drained into `system.log` as line #1 once the
manager rises; after the manager it writes to the file directly. `emergency_log` never does.

**Why:** `emergency_log`'s own contract (2.2) reserves it for "the one who broke reports its
own breakage" — recursion avoidance. A config validator is not the route's self-failure.
Six production call sites in three files used it in the same misplaced position at the time
(documents/wiring ×3, observability_declarations ×1, observability_config ×2).

**How to apply:** when a verdict touches an operator-facing warning, check the ADDRESS by
running (file vs stderr), not the count. Also: the reload path parses the section six
times by design (validate → apply → verify, each with parse + unknown-keys + expand) — a
side-effecting `mode="before"` validator fires per parse, and a wall-clock throttle over it
reports "suppressed: N" where N counts parser passes, not operator actions.
