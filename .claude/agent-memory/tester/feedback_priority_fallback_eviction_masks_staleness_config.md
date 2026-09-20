---
name: priority-fallback-eviction-masks-staleness-config
description: When a bounded-map mechanism has BOTH an unconditional stale-sweep pass and a single-victim priority-eviction fallback, a test that just checks "did the stale candidate survive" can't tell whether staleness config is honored — the fallback picks the same oldest victim either way. Force MULTIPLE simultaneous stale victims so only the stale-sweep (which removes all qualifying entries in one pass) can push the count below the cap.
metadata:
  type: feedback
---

Writing a RED test for Task 2.7 (`observability-closure`) that
`windowed_voice.WindowedVoices` should honor a configurable `stale_windows`
(instead of the hardcoded `_STALE_WINDOWS = 10`), my first draft inserted ONE
stale candidate key, advanced the clock past a short configured threshold, then
triggered a sweep and asserted the stale key was gone. That test would have
passed for the WRONG reason: `_sweep_locked`'s fallback phase (triggered
whenever population still exceeds the cap after the stale pass) evicts exactly
`len - cap` entries ordered by `(is_debtor, timestamp)` — i.e. the single
oldest non-debtor key. If the stale candidate also happens to be the oldest
non-debtor (the natural, easiest-to-write setup), the fallback removes it
ANYWAY even when `_STALE_WINDOWS` is still hardcoded at 10 and the stale-phase
itself did nothing. Final state is identical either way — the test can't
distinguish "removed by configured staleness" from "removed by the capacity
safety net that would fire regardless".

**Why:** caught by building a standalone Python simulation of the sweep logic
(`sim_windowed_voice.py` in scratchpad) and running BOTH the "policy honored"
and "policy still hardcoded" branches through my exact test scenario before
trusting the RED assertion. First attempt gave the same final population (1
survivor) in both branches — a worthless RED spec that would still be red or
green somewhat by luck, not proof.

**How to apply:** when a bounded collection has an unconditional "sweep
everything stale" pass PLUS a fallback that evicts only the minimum needed to
reach the cap, don't test staleness config with a single stale victim — insert
SEVERAL simultaneously-stale non-debtor keys (all older than the SHORT
configured threshold but younger than the OLD hardcoded one) alongside one
debtor (immune to both mechanisms) and one fresh trigger key. The stale-sweep
pass, because it's unconditional and removes every qualifying entry in ONE
pass, drops population *below* the cap when several keys qualify at once — the
single-per-call fallback can never do that. Assert the exact post-sweep
population (computed via a standalone simulation first, not by intuition) —
here: 2 survivors when honored vs. 3 (parked exactly at the cap) when not.
General lesson: before trusting an arithmetic-heavy RED assertion against a
multi-branch eviction/sweep mechanism, simulate both the "fixed" and "still
broken" code paths offline and confirm they actually diverge on your exact
scenario — don't trust hand-traced logic for anything with more than one
elimination phase. Related: [[feedback_dedicated_breaker_threshold_avoids_confound]]
(same shape of bug — one variable's effect confounded by another mechanism
that would produce the same observable outcome).
