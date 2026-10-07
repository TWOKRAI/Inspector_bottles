---
name: gc-finalizer-test-needs-gen0-pin
description: "Тест на «финализатор gc внутри лока» вакуумен в полном прогоне — цикл уходит в gen1; пришпилить gc.disable + set_threshold(1) / a test that relies on gc firing a finalizer inside a lock is vacuous in a full suite"
mechanism: [flaky-tests, concurrency]
role: teamlead
metadata:
  type: feedback
---

A red test for "gc finalizer re-enters a lock" (Task 0.2 F1, `unclosed_roots` + `_roots_lock`) went red alone but gave 0 red in the full `pytest base_manager` under the Lock injection: a gen0 collection during `open_scope`/`own` promoted the abandoned cycle to gen1, so the gen0 pass inside the locked comprehension never finalized it.

**Why:** relying on default thresholds (700) and "the cycle is still young" is scheduler/allocation-history dependent.

**How to apply:** in the worker thread: `gc.collect(); gc.disable()`, build the garbage cycle, then `gc.set_threshold(1); gc.enable()`, call the locked function; restore threshold + `gc.enable()` in `finally`. Verify the injection in the FULL suite (with `-x` and a subprocess `timeout` — a red here holds the lock forever).
