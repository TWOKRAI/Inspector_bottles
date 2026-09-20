---
name: store-kind-ignores-which-manager-wrote-it
description: ObservabilityStore's kind=error is decided purely by log severity (kind_for_severity), not by which manager/tap wrote it — a "kind=error row exists" assertion can be true today even through the wrong (bypassing) path
metadata:
  type: feedback
---

`StoreTapChannel`/`record_display.kind_for_severity` derive a stored record's
`kind` (`log` vs `error`) SOLELY from the record's severity number (`>= ERROR`
→ `error`), regardless of which manager's tap wrote it. So `ctx.log_error(...)`
(a plain diagnostic string through `logger_manager`, NOT through the error
plane / `ctx.health.report_error`) already produces a `kind='error'` row in
`ObservabilityStore` today, on an unfixed codebase — same as a "proper"
incident through `track_error`/`ErrorManager`.

**Why:** found writing an acceptance test for `observability-closure` Task 1.3
("one connector per incident site" — a capture-plugin camera-open failure must
reach the error plane via `ctx.health.report_error`, not `ctx.log_error`). My
first draft asserted "store has exactly one kind=error row for this incident"
as the RED-defining check — but that's already true TODAY via the buggy
`ctx.log_error` path (it's ERROR severity, so it maps to kind=error via the
LOGGER tap, no health/error-manager involvement needed). That assertion alone
would have been a vacuously-green "RED" test — the real gaps are (a) the file
literally named for the error plane (`errors.log`, ErrorManager's own channel)
stays empty (`ctx.log_error` routes to `system.log` via logger_manager only —
confirmed by the project's own C2 probe docstring in `test_error_route.py`),
and (b) `ctx.health.status` stays OK because `report_error` was never called.

**How to apply:** when a criterion says "N rows of kind=X in the store" as
proof that a NEW code path is exercised, first check empirically (grep +
`kind_for_severity`/`record_display.py`) whether the CURRENT buggy path already
produces that count via severity mapping alone. If so, that assertion isn't
RED-defining by itself — pair it with a fact tied to the SPECIFIC manager
(e.g. the literal file content of `errors.log`, or `HealthState.status`/
`error_count`, which only change through the intended connector) so the whole
test function fails for the right reason. See also
[[feedback_a_control_can_exist_and_be_dead]] (same shape: an observable that
looks like it discriminates but doesn't) and
[[feedback_injection_must_use_a_different_lens_than_the_test]].
