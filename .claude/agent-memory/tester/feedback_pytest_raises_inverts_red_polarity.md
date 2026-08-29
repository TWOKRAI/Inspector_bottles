---
name: pytest-raises-inverts-red-polarity
description: In RED mode, wrapping a to-be-implemented-feature call in pytest.raises(SomeError) makes the test PASS today (feature absent) — exact wrong polarity; assert on the real success shape instead so the current exception propagates unwrapped
metadata:
  type: feedback
---

In `MODE: red`, a test that does `with pytest.raises(KeyError): cm.dispatch("not.yet.registered", ...)`
is GREEN right now — dispatch on a missing command really does raise `KeyError`, so the
`pytest.raises` block "successfully" catches it and the test reports PASSED. That is the
opposite of what RED mode requires ("all tests must be red at the end of your run"):
`pytest.raises` is the right idiom for a *regression* test asserting "this call correctly
rejects bad input", but in RED mode the goal is the OPPOSITE polarity — the test must fail
today, and only pass once the feature exists and behaves correctly.

**Why:** found while writing Task 1.1's acceptance suite (`plans/observability-closure/phase-1-invisible-failures.md`,
`multiprocess_framework/modules/process_module/tests/test_process_hooks_acceptance.py`, criterion A8:
`diag.thread_raise`/`diag.warn` commands not yet registered). First draft wrapped
`cm.dispatch("diag.thread_raise", ...)` in `pytest.raises(KeyError)` — ran it, and both A8 tests
showed up as PASSED in the pytest summary while everything else in the file was correctly FAILED.
Caught only because the task's "echo the exact per-test red reason" reporting step forced reading
the actual pytest output line by line, not just skimming "N failed" — a summary count alone
(`11 failed, 2 passed` before the fix) doesn't visually flag which 2 are the wrong-polarity ones
unless you check *why* each one is red or green.

**How to apply:** in RED mode, when a criterion's natural shape is "call X, it currently raises
because X doesn't exist / isn't wired yet" — do NOT wrap the call in `pytest.raises`. Instead call
X directly and assert on the *eventual correct* return shape (fields, values) exactly as the
contract describes it for when X is implemented. The exception X raises today then propagates
UNCAUGHT out of the test body, and pytest reports the test itself as FAILED with that exception
as the traceback reason — which is the correct RED result, and the SAME test becomes a real
positive-behavior check once the implementation lands (no rewrite needed at GREEN time, unlike a
`pytest.raises`-wrapped version which would need to be deleted/replaced entirely).
`pytest.raises` remains correct for testing a *negative* contract that is supposed to stay an
error forever (e.g. `diag.warn(category="NoSuchWarning")` returning `{"success": false, ...}` —
note: even that isn't a raised exception in the target contract, so still no `pytest.raises`
there either — only for cases where raising is the permanently-intended behavior, e.g. malformed
input that the API contract says must raise).
