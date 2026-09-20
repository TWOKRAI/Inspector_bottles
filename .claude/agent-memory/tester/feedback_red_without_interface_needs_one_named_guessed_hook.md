---
name: red-without-interface-needs-one-named-guessed-hook
description: writing RED acceptance tests for a genuinely new mechanism with no interface.py — isolate the one unavoidable guessed API name, keep everything else on existing/observable surfaces
metadata:
  type: feedback
---

Task 2.1 plana `observability-closure` (numbers-plane policy gate, Ф2) had no
`interface.py` and no scaffolding anywhere (grepped the whole repo — zero hits
for any plausible symbol name). Only a plan text ("порт спрашивает
policy.resolve(path) до NumberRecord") and 8 acceptance criteria. Writing 8
independent RED tests against this required SOME way to wire an
`ObservationPolicy` into the not-yet-existing gate.

**Rule applied:** minimize the guessed surface to exactly ONE symbol, reused
across every test that needs it, named by analogy with the file's OWN existing
idiom (`attach_observation_port`, `attach_observability_hub` already exist on
the same class → guessed `attach_numbers_policy` fits the same shape). Every
OTHER assertion in every test targets an ALREADY-EXISTING, real API
(`StatsManager.get_stats()`, `.observability_readback()`, `expand_observability()`,
`ObservableMixin._record_metric`, `caplog` against the project's own established
`emergency_log` warning idiom) or a criterion-literal contract name given by the
plan itself (`numbers_policy_dropped`, `plane_disabled`, `stats.policy`,
`dropped_by_rule`).

**Result:** 4 of 9 tests share ONE blocking `AttributeError` line (the guessed
hook) — by design, not sloppiness; the other 5 are independent and fail with
distinct, literal-showing `AssertionError`s (e.g. `enable_logging: False`
still using the OLD `stats.enabled` mapping, `plane_disabled` key absent,
`log_snapshots` attribute absent). Verified all 9 fail for the intended reason
by reading each traceback, not just the summary line count.

**Where genuinely unsure which of two objects would hold a value** (does
`numbers_policy_dropped` live on `StatsManager` or on the port that makes the
drop decision? does `stats.policy` readback come from
`StatsManager.observability_readback()` or from
`observability_wiring.stats_plane_report(svc)`?) — wrote the assertion to
check BOTH plausible addresses and only fail if NEITHER has it, documented as
a hedge in the test's own docstring, not hidden. This keeps the test useful as
a real regression check under either implementation choice, instead of pinning
one guess that would still fail after a correct-but-differently-shaped fix.

**Why:** a test that hard-codes a guessed private method name AND never gets
implemented under that name stays red forever even after correct
implementation — bad ТЗ. Concentrating the guess into ONE named symbol (stated
loudly in the module docstring, with a grep-confirmed "nothing exists yet"
disclosure) keeps the failure diagnosable and cheap to fix (rename one call
site) rather than scattered across many different wrong guesses.

**How to apply:** next time a Tester gets a freeform brief with acceptance
criteria but no `interface.py` and no prior scaffolding — grep first for every
plausible symbol name (proves nothing exists, not just "I didn't see it"),
then design tests in TWO tiers: (a) tests reachable via 100%-existing public
API (schema fields via `getattr`, `expand_*` facades, existing readback
methods, existing counters) — write these first, they need zero guessing; (b)
tests that need a new wiring point — pick ONE consistent guessed name by
analogy with the codebase's own naming idiom, use it everywhere such wiring is
needed, and say so loudly in the file's docstring rather than pretending
confidence. See also [[feedback_tester_once_per_mechanism_before_the_code]],
[[feedback_tester_blindness_needs_a_worktree]].
