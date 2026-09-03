---
name: wired-harness-missing-introspect-commands
description: _wired() in test_observation_policy_review_f4.py registers only _register_observability_commands() (config.reload, telemetry.reconfigure) — NOT introspect.telemetry/introspect.observability. Tests needing those must also call _register_introspect_commands().
metadata:
  type: feedback
---

`_wired(tmp_path)` in `modules/process_module/tests/test_observation_policy_review_f4.py:64`
(the harness CLAUDE.md explicitly points testers to for "operator-visible claim → real
handler" tests) calls `bc._register_observability_commands()` only. That method registers
`config.reload`, `telemetry.reconfigure`, `logger.sink.*` — it does NOT register
`introspect.telemetry` or `introspect.observability`. Those live in a SEPARATE
`bc._register_introspect_commands()` (`builtin_commands.py:639`).

Proof: `test_introspect_telemetry.py`'s own local harness (`_make`, line ~90) calls BOTH
`bc._register_introspect_commands()` AND `bc._register_observability_commands()` — if
`_register_observability_commands()` alone were enough, that file wouldn't need the first
call. Calling `handlers["introspect.telemetry"]` against plain `_wired()`'s output raises
`KeyError`, not a meaningful test failure — a harness gap, not a finding.

**Why:** discovered writing RED tests for Task 2.3 of `observability-closure`
(`test_f2_task23_honest_tick.py`) that needed `introspect.telemetry`/`introspect.observability`
readback through the real command layer. Assumed `_wired()` was the complete "wired process"
fixture (CLAUDE.md's own wording implies this) and would have gotten a confusing `KeyError`
unrelated to the actual property under test had I not cross-checked against
`test_introspect_telemetry.py`'s own setup first.

**How to apply:** when a test needs `introspect.*` commands AND real command wiring (not just
`config.reload`/`telemetry.reconfigure`), don't call `_wired()` as-is — `_wired()` doesn't
return the `BuiltinCommands` instance (`bc`), so you can't add the missing registration to its
result afterward. Either write a local copy of `_wired`'s body with
`bc._register_introspect_commands()` added (what `test_f2_task23_honest_tick.py` does, as
`_wired_with_introspect`), or use `test_introspect_telemetry.py`'s own `_make()` pattern
directly. For tests that only need `config.reload`/`telemetry.reconfigure`, plain `_wired()`
is sufficient and should still be preferred (don't over-extend by default).
