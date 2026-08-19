---
name: negative-wording-assertion-needs-an-existence-anchor
description: A test asserting a log/message must NOT say wrong-thing-X is vacuously green if nothing was ever logged — pair it with an existence assertion in the same test so a missing feature is the failure reason, not an absent string match
metadata:
  type: feedback
---

When an acceptance criterion has the shape "if the code logs/reports outcome O, the message
must not falsely claim Q" (e.g. "the disabled-gate log must not say 'no section' when a
section exists, just at the wrong address" — RT-2, telemetry-stage6, 2026-08-18, criterion
B5), a standalone test of the form `assert "wrong claim" not in log_text` is **vacuously
green today** whenever the feature that would produce the log doesn't exist yet — `log_text`
is `""`, and `"wrong claim" not in ""` is trivially `True`. This is the same "unconnected
driver reads as a clean zero" trap as [[feedback_unconnected_driver_reads_as_a_clean_zero]],
one level up: here the "driver" is the logging call itself, not a downstream receiver.

**Why:** caught before running, while writing `test_gate_config_address_acceptance.py`.
Nearly shipped the wording check (`"секции нет" not in joined`) as its own isolated test —
it would have stayed green through the entire RED phase for the wrong reason (no log call at
all), given no signal when the log gets added later with the exact wrong wording, and only
fail if someone happened to run it AFTER adding a correct-sounding-but-wrong log line, which
is not guaranteed to ever happen in a normal review pass.

**How to apply:** put the existence assertion (`assert services.logs, "..."`) BEFORE the
wording assertion in the SAME test, not as a separate test. Today it fails on the existence
line (missing log — the real, dominant defect) with a clear reason; once the log gets added,
the SAME test starts checking the wording property it was written to protect, with no
separate vacuous-pass test left hanging around as false coverage. Don't split "does it log"
and "is the wording honest" into two tests here — the second one alone would be the vacuous
one; keeping them together is deliberate, not a violation of one-test-one-check (it is one
check: "the diagnostic for this branch is present and honest").
