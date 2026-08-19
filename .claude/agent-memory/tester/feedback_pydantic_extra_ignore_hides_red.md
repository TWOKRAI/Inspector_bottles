---
name: pydantic-schemabase-extra-ignore-hides-red
description: SchemaBase (Pydantic v2, extra=ignore) silently drops not-yet-declared constructor kwargs — a RED test for "add a new field" must assert the attribute directly, not just the kwarg's downstream effect
metadata:
  type: feedback
---

Every `SchemaBase`-derived config/registry in this project (Pydantic v2) inherits the
default `extra='ignore'` — confirmed empirically on `TelemetryPublishConfig` and via the
existing test `test_unknown_keys_ignored` in `test_telemetry_publish_config.py`. Passing a
field that doesn't exist YET as a constructor kwarg (e.g. `TelemetryPublishConfig(default_enabled=False)`
before the field is implemented) does **not** raise anything — it is silently dropped, the
object constructs fine, and only a plain Python `AttributeError` shows up, and only if you
later touch the attribute directly.

**Why:** found writing RED acceptance tests for `default_enabled: bool` on
`TelemetryPublishConfig` (`telemetry-stage6`, 2026-08-18). A test that ONLY checks
`resolve()`/behavioral output through the new kwarg can be accidentally GREEN today: e.g.
`TelemetryPublishConfig(default_enabled=False, metrics={"m": MetricRule(enabled=True)}).resolve("m")`
returns `(True, ...)` both before AND after the field exists, because an explicitly-listed
metric's rule always governs itself regardless of any dropped/well-formed `default_enabled` —
the kwarg being silently ignored is invisible unless the test also exercises an UNLISTED
metric (whose current behavior actually differs) or checks the attribute.

**How to apply:** in RED mode, for "add a new field to a `SchemaBase`-derived config", put a
**direct attribute access** as the first assertion after construction —
`assert cfg.<new_field> is <expected>` — never rely only on a kwarg + downstream-behavior
check. Pydantic v2 raises a clean, deterministic
`AttributeError: '<Class>' object has no attribute '<field>'` for this (no
`pydantic.ValidationError`, no `__getattr__` fallback without `extra="allow"` — verified live,
not assumed). This both guarantees RED today and remains a legitimate assertion after
implementation (it confirms the constructor actually wires the value, catching e.g. a
misplaced `alias=` that would otherwise hide behind resolve()-only checks). Companion
technique used in the same task: [[test-live-telemetry-gate-without-full-boot]].
