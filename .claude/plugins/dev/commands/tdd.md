---
description: Focused contract-first RED → GREEN → [REFACTOR] loop for one unit (TDD) — standalone extract of /dev:pipeline §2
---

A narrow **TDD cycle for one unit/behavior**: **RED → GREEN → [REFACTOR]**. This is the
thinnest of the three implementation modes — no planning (manager), no mandatory
INTERFACE stage, no full regression run, no review loop.

**Where it sits among the commands:**
- `/dev:pipeline` — the full cycle (plan → implement → test → review → ship).
- `/dev:implement` — one Task X.Y from a plan along the contract branch (`new-*` → INTERFACE→RED→GREEN),
  with Refs tracing.
- `/dev:tdd` (this one) — one function/behavior, test-first, when the contract already
  exists (`impl-only`) or a quick red→green is needed without plan ceremony.

Input: $ARGUMENTS — what to cover (function/method + desired behavior / acceptance).
If $ARGUMENTS is empty:
> Specify the unit and behavior: `/dev:tdd <function> should <behavior>` or
> `/dev:tdd tests/unit/test_x.py::test_y — <expected>`

## Cycle

**RED** — run **tester** (Sonnet) in `MODE: red`. Parameters are passed as a header in the
first lines of the prompt (see `agents/tester.md` → "How the orchestrator passes parameters"): at
minimum `MODE: red`, `TASK:`, and `INTERFACE:`/`MODULE_CONTRACT:` if an in-code contract exists.
- One failing test per **one** Pre/Post line (or one acceptance criterion, if there's no formal
  contract — the tester flags this in the report).
- The tester reads **only** the contract/spec, **not** `_impl/`, and **demonstrates** the failure with
  the right error type (`AssertionError` for `impl-only`; `NotImplementedError`/`AttributeError` if
  the symbol doesn't exist yet). `ImportError`/`SyntaxError` = broken setup, fix it, don't count it as RED.
- If the test **passes** → the test is wrong (it tests current behavior, not the desired one), rewrite it.
- Commit: `test(<scope>): failing test for <unit>` (+ `Refs:`, if a plan exists for the slug).

**GREEN** — run **developer** (Sonnet) or **teamlead** (Opus, if Senior+):
- Pass the path to the RED test (and to `interface.py`, if it exists) — the agent **reads** the
  contract, doesn't guess it.
- **Minimal** implementation in `_impl/`, so the RED test passes and Pre/Post are honored. No
  over-engineering for the future.
- The agent **does not edit** the RED test or the contract to fit broken code (anti-cheat). A
  wrong contract → back to `manager`/INTERFACE, not a patch-up.
- Commit: `feat(<scope>): impl for <unit>` (+ `Refs:`).

**REFACTOR** (optional) — if GREEN left obvious debt: clean up in the same context, tests
green after each change; the public contract is not touched.

**The canonical algorithm for each stage** (Pocock anti-cheat rationale, exact commit messages,
RED error types by contract branch, failure recovery) — `/dev:pipeline` §2 (single source of
truth). Not duplicated here — read it when in doubt.

## When to call

- Test-first discipline is needed on **one** unit right now, without a full plan/pipeline.
- A bugfix following "test reproducing the bug first → then the fix" (`impl-only`).
- The contract (`interface.py` / docstring) already exists — only a red→green is needed.

## When NOT to call

- A new public module (needs an INTERFACE stage) → `/dev:implement` (branch `new-*`).
- Several related Tasks / review and regression needed → `/dev:pipeline`.
- Config / docs / dep-bump (`n/a` — TDD doesn't apply) → edit directly.
- Diagnosing a failing test with a non-obvious cause → `/dev:debug` (skill `systematic-debugging`),
  not "write a new test".

## Refs tracing

If a plan exists for the current slug (`plans/YYYY-MM-DD_<slug>.md` or `.../phase-N.md`) — every
stage commit carries the trailer `Refs: <exact path to the plan>` (as in `/dev:implement` §3). No plan
(a quick unit outside planned work) — don't block, but warn the user.

Unit: $ARGUMENTS
