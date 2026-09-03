---
name: windowed-voice-throttle-collides-with-sibling-tests
description: Adding a process-wide windowed_voice throttle to a validator makes any OTHER test in the same pytest session that expects "a fresh voice on this call" flaky/red, even within one file
metadata:
  type: feedback
---

Task 2.12 of `observability-closure`: `ObservabilityStatsConfig._complain_about_repurposed_enabled`
was changed from "warn every validation" to "warn at most once per
`observability.voices.default_window_sec` (5.0s), keyed by `stats.enabled.repurposed`,
via the shared process-wide `windowed_voice.process_voices()` singleton" — exactly
as specified (window by key, not a process flag, per Р-12).

**Consequence, confirmed by running, not assumed:** any pre-existing test elsewhere
in the framework that calls `ObservabilityConfig.model_validate({"stats": {"enabled":
False}})` (directly, or indirectly through `expand_observability`/`config.reload`) and
asserts a voice appeared now silently fails if ANOTHER such call already happened
within the last 5s of wall-clock test time in the same pytest process — including
calls from an *earlier test in the very same file* that don't check `caplog` at all.

Reproduced twice, deterministically:
- `statistics_module/tests/test_f2_numbers_policy_acceptance.py::test_c7_...` fails
  **even run in total isolation** (`pytest test_f2_numbers_policy_acceptance.py`
  alone) — because `test_c3_...` and `test_c4b_...`, defined earlier in the SAME
  file, each call `expand_observability({"stats": {"enabled": False, ...}})` and
  consume the window before `test_c7` gets to it.
- `process_module/tests/test_f2_task29_fingerprint_probe.py::
  TestTheProbeDoesNotSpeakForTheOperator::test_the_operators_own_disabling_still_speaks`
  fails only in the full-suite run, because `test_f2_task22_schema_wiring.py`'s
  `TestFullSectionRoundTripHasNoUnverifiablePaths::test_unverifiable_is_empty` (which
  sorts earlier alphabetically) reloads a section containing `stats.enabled: false`
  first.

**Why:** the window state lives on a process-wide singleton
(`windowed_voice._PROCESS_VOICES`), and only tests that explicitly call
`reset_process_voices()`/`reset_voice_counters()` (autouse fixture) are isolated from
it. Tests written before the throttle existed have no reason to know they need this
fixture, and adding the fixture retroactively to every sibling is a cross-file change
outside a single task's normal scope.

**How to apply:** when a task adds voice/window throttling (this project's
`windowed_voice` mechanism) to code that other tests already exercise with the
now-throttled input, budget time to grep for every existing test asserting "a warning
appears" for that exact input, run them TOGETHER with the new code (not just the new
test file in isolation), and expect at least one to go red. Do not assume "my new
tests are green" means neighbors are unaffected — the regression here was invisible
running the new files alone and only appeared once the wider suite ran. If fixing the
siblings is out of the task's allowed file list, name the exact failing test id(s) and
the literal assertion error in the report rather than silently shipping a regression;
this is a design tension (global throttle vs. per-test isolation) for the orchestrator
to resolve (e.g. add a shared `autouse` `reset_process_voices()` fixture at a
`conftest.py` scope, in a follow-up task), not something to paper over.

See also [[feedback_readback_confirms_faster_than_the_mechanism_reapplies]] — another
case in this same plan where a mechanism's OWN correct behavior broke an assumption a
sibling test had baked in.
