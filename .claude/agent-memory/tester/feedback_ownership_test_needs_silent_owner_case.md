---
name: ownership-test-needs-silent-owner-case
description: an independent ownership-collision suite that only tests "owner publishes + impostor publishes" is not enough — add the case where the owner declared but did NOT publish this tick
metadata:
  type: feedback
---

When testing a "name ownership" contract (a leaf value is trusted only from its
declared owner), a test where the real owner ALSO publishes on the same tick can
pass even with **no ownership check at all** — merge overlay order (owner's
write applied after the impostor's) silently produces the right answer. This is
exactly what S-8 (`telemetry-stage6`) flagged: the earlier acceptance
(`test_plugin_levels_ownership_acceptance.py`, criterion П1) only covered
plugin-vs-framework, where the framework always overlays its own value on the
same tick — so it stayed green with the ownership rule fully absent.

The differentiator is the **silent-owner** case: owner declared the name but did
not publish anything this tick, and an impostor publishes under that name. If
the rule is "leaf comes from the last write" (order-based), the impostor's value
wins because there is nothing to overlay it with. If the rule is real ownership,
the leaf is absent entirely. Only this case tells the two mechanisms apart.

**Why:** found while writing S-8's `test_plugin_levels_ownership_collision_acceptance.py`
— the brief itself named this as "the main differentiator" (О2), and explained
that the *previous* acceptance suite's green run proved nothing about ownership
because overlay order was doing the work instead.

**How to apply:** whenever a spec/brief asks to test "ownership" or "authority
over a name/resource" between two writers, always include a case with the true
owner silent/absent this cycle, not just live-vs-impostor. A suite without that
case can be green under a mechanism that has no ownership check at all — the
break-injection this repo requires (project CLAUDE.md, "Test authorship") would
catch it, but it is cheaper to write the differentiating case up front. See also
[[feedback_negative_wording_assertion_needs_an_existence_anchor]] for the
sibling lesson about tests that pass vacuously when nothing fires.
