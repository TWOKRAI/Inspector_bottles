---
name: dedicated-breaker-threshold-avoids-confound
description: When testing HealthState.report_error repeat counts, inject a CircuitBreaker with a huge fail_threshold — otherwise N>=5 repeats trip DEFAULT_FAIL_THRESHOLD and its own set_status() call injects an unrelated log line into your voice-count assertion.
metadata:
  type: feedback
---

`HealthState.report_error` feeds a `CircuitBreaker` (default `fail_threshold=5`,
`multiprocess_framework/modules/process_module/health/breaker.py`) on every call,
independently of the throttle/voice mechanism under test. A test that fires N>=5
repeats of the same key to check "at most 1 voice within the window" will get a
SECOND, unrelated log line once the breaker opens — its `set_status(DEGRADED, ...)`
calls `_safe_log` unconditionally on state change, outside the throttle gate
entirely.

Confirmed live (2026-08-31, observability-closure Task 1.3a acceptance tests): a
5-repeat test with a default breaker produced 1 extra log call ("breaker open: ...
5 подряд") that had nothing to do with the throttle-window property being tested.

**Why:** the breaker and the throttle/voice window are two separate mechanisms
that both call the same `log` callback. Confounding them makes a failing test's
diff misleading (you'd see 2 log calls and wrongly conclude the throttle isn't
working, when it's the breaker firing).

**How to apply:** when constructing `HealthState` for a test that counts log/voice
calls across >=5 repeats of one key, always pass an explicit
`breaker=CircuitBreaker(fail_threshold=<huge>, cooldown_sec=<huge>, clock=...)` to
neutralize it. Same applies to any test that reuses one HealthState instance
across many repeats of the same exception type+context.

See also [[feedback_windowed_voice_is_a_process_wide_singleton]].
