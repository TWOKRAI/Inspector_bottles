---
name: feedback-fake-missing-attribute-vacuous-test
description: A test fake missing an attribute the rule reads makes the test green for the wrong reason — the earlier branch rejects it
metadata:
  type: feedback
---

A fake object in a test must carry EVERY attribute the rule under test reads, with a value that passes
all branches except the one the test targets. Otherwise an earlier branch rejects the fake and the test
is green for the wrong reason.

Measured 2026-09-30 (pipeline-node-timing T1, sandbox compatibility rule): the rule judged inputs by
`getattr(p, "dtype", "")`; `FakePort` in `test_check_side_effect_category_disabled` and
`test_check_multi_input_port_disabled` had no `dtype`, so "" != "image/bgr" closed the plugin before the
category / count check. Removing the whole side-effect category list or the `len(required) > 1` clause
left both tests green. Found only by lead's break-injection (J3, J5), not by author or reviewer.

**Why:** a rule with a chain of rejections hides which branch rejected; `ok is False` alone cannot tell.
**How to apply:** when writing or reviewing such tests, (1) give fakes the attributes of a VALID input and
break only the targeted one; (2) assert the rejection REASON, not just `ok is False`; (3) break-inject
each branch separately — see [[injection-scripts-on-committed-code]].
