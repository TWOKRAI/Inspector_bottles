---
name: config-reload-ttl-addressing-guard
description: config.reload refuses ttl on a throttle-only payload for an unrelated pre-existing reason — don't mistake that refusal for the property under test
metadata:
  type: feedback
---

`config.reload` has a pre-existing, unrelated guard: if the inline payload carries
`ttl` but has neither `observability` nor `telemetry.publish` — only
`telemetry.throttle` — it refuses with reason "ttl нечему адресовать: нет ни
inline-секции observability, ни telemetry.publish; throttle — центральная
политика оркестратора, срока у неё нет". This fires **regardless of whether a
throttle receiver exists** (confirmed live with and without a wired
`StateStoreManager`/`ThrottleMiddleware`).

**Why:** Found while writing acceptance tests for Task 3.1 (telemetry-stage6,
"no receiver → refuse, don't succeed with a dead slot"). A test asserting
`success is False` on `config.reload({"telemetry": {"throttle": {...}}, "ttl": 60})`
against a no-receiver process passed **today**, before any fix — but for this
unrelated ttl-addressing guard, not for the receiver check. That's a vacuous
green: it would keep passing whether or not the real fix ever lands. See
[[feedback_test_survived_its_own_break]] — same shape of trap, caught by
querying the live handler output before trusting the assertion.

The `telemetry.reconfigure` door does NOT have this guard — `{"throttle": {...},
"ttl": 60}` there returns `success=True, applied={"throttle": False}, ttl_sec=60.0`
(consumes an L3 slot with a dead flag — the real Task 3.1 bug), no ttl-addressing
refusal. The two doors diverge on ttl handling for throttle-only payloads in a
way that has nothing to do with the receiver-existence question.

**How to apply:** When testing throttle/L3 behavior via `config.reload`, either
omit `ttl` entirely (a *default* TTL still gets armed on a no-receiver throttle
command today — confirmed: `telemetry.throttle` lands in `session_keys()` with a
300s default even with no explicit `ttl` in the payload) or include an
`observability`/`telemetry.publish` section alongside `throttle` so the
ttl-addressing guard doesn't preempt the check you actually want to exercise.
Always print/inspect the live handler response before asserting on `success`
when a command has more than one guard that can produce `False` — a matching
boolean is not proof of the right cause.
