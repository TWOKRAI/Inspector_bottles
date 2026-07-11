---
name: systematic-debugging
description: >
  Disciplined root-cause debugging for a failing test or a reproduced
  regression — reproduce first, form at least two hypotheses, test the
  most-likely one first, fix the cause (not the symptom) or escalate.
  Activates when a test is red, a regression is reproduced, a runtime
  error is unclear, or before /dev:debug runs — NOT on every mention of
  a bug. Triggers: "why is this failing", "root cause", "test keeps
  failing", "regression after", "systematic debugging", "/systematic-debugging".
---

# Systematic debugging

This skill formalizes the method in the `debugger` agent into a discipline any
agent can follow when it hits a **non-obvious** failure. The goal: find the one
real cause and fix it (or hand off a precise diagnosis) — never guess-and-patch,
never mask the symptom, never edit the test to make red go green.

The cheapest debugging is structured debugging: a reproduction you can run on
demand plus two competing hypotheses beats ten speculative edits.

## When this applies

Use the loop when **all** of the following hold:

- A test is **red**, a regression is **reproduced**, or a runtime error is unclear.
- The cause is **not obvious** from a glance (not a one-character typo).
- You can run the failure (or are about to make it runnable).

If you cannot yet reproduce it, your first job is to make it reproducible — see step 1.

## The loop

1. **Reproduce first (mandatory).** Get a single command that fails on demand:
   `pytest <path>::<test> -v -x`, or a minimal manual scenario. If you cannot
   reproduce it → STOP and report exactly what is needed to reproduce. Do not
   theorize about a bug you cannot trigger.
2. **Gather evidence.** Stack trace (which line, which error type), variable values
   at the failure point (`pytest -s`, `print`, `--pdb`), recent history
   (`git log -5`, `git diff HEAD~1`), and `git blame <file> <line>`. Use the
   project's MCP routing for context (`qex:search_code`; `codegraph_explore`
   for the exact call chain; `context7:query-docs` for suspected library behaviour)
   and fall back to `Grep`/`git log` when those are not connected.
3. **Form at least two hypotheses.** Hypothesis A (most likely) and Hypothesis B
   (alternative). A single hypothesis is a guess; two competing ones force evidence.
4. **Test the most-likely hypothesis first** (ranked by `git blame` + change recency).
   Isolate one variable at a time — comment a block, mock an input, simplify the
   test, add a temporary `print`/`logger.debug`. For a regression that is **not**
   local, `git bisect` to the first bad commit (see below).
5. **Find the root cause** — one line, one wrong invariant, one race. "The test is
   bad" is a conclusion you must *prove*, not assume: tests are usually right, code
   is usually wrong.
6. **Fix or escalate:**
   - In scope (1–5 lines, obvious once the cause is known) → apply the **minimal**
     fix, re-run the failing command, confirm green, confirm adjacent tests still pass.
   - Out of scope (architectural, >5 lines, needs a decision) → produce a diagnosis
     (root cause + evidence + proposed fix) and hand off to `developer`/`teamlead`.

## Bisect for non-local regressions

When a regression's cause is not in the recently-touched code:

```
git bisect start
git bisect bad                 # current commit is broken
git bisect good <known-good>   # last commit you know worked
# run the repro at each step; mark good/bad until git names the first bad commit
git bisect reset
```

The first bad commit usually contains the cause directly.

## Escalation

Stop and hand off to `teamlead` (Opus), or `investigator` for read-only deep
cross-module analysis, when:

- 3+ hypotheses are all rejected and the root cause is still unclear.
- The failure looks like a **race condition** or memory corruption.
- The fix would require an **architecture change** (not a local 1–5 line fix).
- The bug spans process boundaries / IPC / state propagation across modules
  (`investigator` is built for exactly this).

## When NOT to use this skill

- Obvious one-character typo or import error you can see directly → just fix it.
- The feature is **not implemented yet** → that is `implement` work, not debugging.
- A full refactor is needed → that is `teamlead`, not a debugging loop.
- A green test you simply want to extend → write the test (`/dev:tdd`), don't debug.

## Output format

Mirror the `debugger` agent's report shapes (it is the source of truth for the
exact templates):

```
ROOT CAUSE FOUND
File: <path>:<line>
Type: <logic / race / typing / config / dependency>
Reproduction: <exact command>
Cause: <1-2 sentences>
Evidence: <log / variable values / git blame>
Proposed fix: <specific lines>
Test after fix: <how to verify>
```

or, when you fixed it yourself:

```
FIXED
File: <path>:<line> — <N lines>
Root cause: <short explanation>
Verified: <command> PASS · regression gone · adjacent tests pass
```

Always show your work — evidence (log, diff, blame), not "seems fixed".
