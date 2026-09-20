# {{MODULE_NAME}} — Context

Per-module knowledge for agents and people. Created at the module root
(`<package>/<module>/CONTEXT.md`). All sections are **optional** — keep
only what's non-trivial and useful to know before editing the code.

Aggregator (`scripts/aggregate_context`) collects CONTEXT.md from all
modules into `docs/PROJECT_CONTEXT.md`.

---

## Purpose

What the module does and why. 1-3 sentences. Something that can't be
picked up from a quick glance at `__init__.py` / `interface.py`.

_Example: "Routes requests between the API and the worker pool.
Manages backpressure via a bounded queue. Entry point — `dispatch()`."_

## Key decisions

Links to ADRs (module-local or global) that shape its design.
If there's no ADR — a short anchor phrase.

- `ADR-{{CODE}}-001` — choice of threading model (see `DECISIONS.md`)
- `ADR-007` (global) — unified message contracts schema
- _or just:_ "Uses a state machine instead of callbacks because of reentrancy"

## Gotchas

Footguns, non-obvious traps, surprising behavior. **This is the most
valuable section** for an agent. List what doesn't follow from the code
and what could accidentally break.

- Don't call from the main thread — blocks the UI event loop.
- `register()` is idempotent only for the same `(name, version)`.
  With a different version — a silent conflict follows.
- `close()` doesn't cancel already-accepted tasks, only stops accepting new ones.

## Glossary

Local terms — words that mean something different in this module than
in the project/industry at large.

- **Token** — opaque worker id (NOT a JWT, NOT an access token).
- **Snapshot** — a copy of the queue without removing elements (not a git snapshot).

## Open questions

What's deliberately left unresolved. When an agent sees these questions
it knows not to touch that area without checking with the author.

- [ ] Backpressure strategy during regional failover — currently a NO-OP.
- [ ] Latency metrics: percentile or mean? Currently mean.

## Migration notes

Important migrations the code or data went through. Helps make sense of
artifacts ("why does legacy `_old_dispatch()` still live here").

- 2026-03-15 — migrated from `multiprocessing.Queue` to `asyncio.Queue`.
  `_old_dispatch()` kept for backward compatibility until v3.0.
- 2026-05-01 — renamed `submit()` → `enqueue()`. The old name was removed.

---

**Stability:** this file is hand-written, the aggregator does NOT overwrite it.
Update it on significant module changes. The aggregator only collects into
the summary index — text outside the markers in `docs/PROJECT_CONTEXT.md`
is also left untouched.
