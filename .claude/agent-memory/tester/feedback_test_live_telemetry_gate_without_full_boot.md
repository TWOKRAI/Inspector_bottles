---
name: test-live-telemetry-gate-without-full-boot
description: To test "a process brought up with telemetry.publish.X" claims, drive ProcessHeartbeat._build_telemetry_gate() with a minimal duck-typed services fake instead of booting a real system/backend_ctl
metadata:
  type: feedback
---

When an acceptance criterion wants a property proven on the LIVE gate (not just on
`TelemetryPublishConfig.resolve()` in isolation) — e.g. "a process brought up with
`telemetry.publish.<X>` does/doesn't publish metric Y" — the cheap, already-precedented way
to test this in `process_module` is a minimal fake, not a real boot:

```python
class _MinimalServices:
    def __init__(self, config: dict) -> None:
        self._config = config
    def get_config(self, key: str, default=None):
        return self._config.get(key, default)

hb = ProcessHeartbeat(_MinimalServices({"telemetry": {"publish": {...}}}))
gate = hb._build_telemetry_gate()      # None if no telemetry/publish section
due = gate.due_metrics(now=0.0)        # synchronous, no clock/thread hazard
```

`_build_telemetry_gate()` only ever calls `services.get_config(key, default)` on the services
object — confirmed by reading it end to end, including `_warn_capped_metrics` /
`_warn_unknown_metrics`, which it also calls: both are no-ops (never touch `log_warning`) when
`tick_sec` is unset and `metrics` is empty, so the minimal fake needs no logging methods for
that shape of config. Precedent: `test_telemetry_gate.py::TestBuildTelemetryGate` already uses
this exact pattern (there with a fuller `_FakeServices`/`_CountingProxy`).

**Why:** found RED-testing the `default_enabled` field (`telemetry-stage6`, 2026-08-18) — the
criterion explicitly demanded the property hold on the live gate including a metric declared
by a PLUGIN (`declare_metric`), not just framework names. A real system boot (backend_ctl)
would also work but is heavy and order-dependent; this harness gets the same live-gate
coverage synchronously and in-process, with zero hang risk — confirmed by reading the call
chain (no threads/IO anywhere in `_build_telemetry_gate`/`due_metrics`), so no daemon-thread
wrapper was needed despite the general "gate/tick calls might block" caution.

**Pair with two things:**
1. `gated_metrics()` is a GLOBAL, session-shared catalog populated by `declare_metric()`
   import side effects. Explicitly `import` both `heartbeat.process_heartbeat` and
   `heartbeat.telemetry` at the top of the test file (matches the precedent/comment already
   in `test_telemetry_publish_config.py`), and if the test declares its own simulated plugin
   metric, clean it up with `forget_declarations(KIND_METRIC, names={...})` in a `finally` —
   otherwise it leaks into sibling tests in the same pytest session (this exact class of bug
   was already reproduced historically in this codebase: "семь телеметрийных тестов краснели
   ТОЛЬКО в полном прогоне").
2. "Unconnected driver reads as a clean zero" — pair the "gate silences everything" assertion
   with a control run of the SAME harness (same fake, same call path) that is expected to
   stay GREEN today (e.g. the same config minus the field under test). Without that control, a
   broken `_build_telemetry_gate` that always returns an empty/`None` gate would make the RED
   test pass for the wrong reason once "fixed", and nothing would catch it.

See also [[pydantic-schemabase-extra-ignore-hides-red]] for the companion schema-level
technique used in the same task.
