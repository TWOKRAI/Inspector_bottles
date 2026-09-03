---
name: feedback-readback-confirms-faster-than-the-mechanism-reapplies
description: adding a config path to a verifier's identity-mapped readback can make config.reload report "confirmed" while the underlying live resource still runs on the old value — check every field for its OWN re-application cadence, not just its readback path
metadata:
  type: feedback
---

When a schema field's live effect is set up ONCE at process wire-time (e.g. a persistent
resource's write-threshold registered via `add_tap(..., min_level=...)`) and a *separate*
per-request cache is refreshed on every `config.reload` (e.g. a sweep-policy dict read fresh
from layers), adding the field to the verifier's readback (`IDENTITY_SECTION_KEYS` /
`observability_effective`) makes `config_reload_verified` answer `confirmed` for BOTH — because
the readback source is the config layer itself (already updated), not the live mechanism.

**Why:** `observability_verified` compares "what the request asked" against "what
`observability_effective` reports" — and if the readback function's source for a field is the
resolved config layer (or a cache the caller happens to refresh on this same reload), it will
always agree with the request the instant the layer write succeeds, regardless of whether the
live consumer (a tap threshold, a running thread's parameter, a socket already bound) actually
picked it up. This is the exact "readback = эхо запроса, а не то, что происходит" trap the whole
`observability-closure` plan exists to fight — except now it can happen INSIDE the very
mechanism built to fight it, one field at a time, silently, because different fields of the same
schema section can have different re-application cadences without anyone noticing.

**How to apply:** when wiring a new config field into `observability_effective`/
`IDENTITY_SECTION_KEYS`, ask separately for THAT SPECIFIC FIELD: (a) does a live-behavior
consumer exist that was configured once and never revisited, or (b) does every `config.reload`
actually re-touch the consumer. Don't assume a whole subsection is uniform — in
`ObservabilityHistoryConfig` (Task 2.2), `max_rows`/`max_age_sec`/`purge_interval_sec` got a
one-line fix (refresh the cache dict on every reload) while `level` needed rewiring a live tap's
registered threshold (`StoreTapChannel` via `add_tap`/`remove_tap`) — same section, same
readback branch, two different real answers. Name the gap explicitly in an ADR if you don't close
it (don't let "readback says confirmed" stand in for "verified live"); a live stand test with
before/after counts (not just `verdict == "confirmed"`) is the only thing that actually catches
this class.

Measured on `plans/observability-closure/phase-2-one-policy.md` Task 2.2 (2026-09-02): the
acceptance criterion explicitly required "стор перестаёт принимать INFO (пара до/после по
счётчику строк)" for `history.level` — a live effect — while the RED test suite the task shipped
with only checked `verified.verdict == "confirmed"` (config-layer honesty), which is satisfiable
without ever touching the live tap. Named as an open item in ADR-PM-047 rather than silently
claimed closed.

See also [[project_observability_facade_extension]] for the sibling "three points of the road"
discipline (schema → facade → readback) this same task extended a fourth time.
