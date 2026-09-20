---
description: Opt-in bounded test-suite triage — run the suite, diagnose failures, propose fixes (human approves). Hard cap 3 iterations / 50k tokens; ai-judge owns the stop-condition. Never auto-runs.
---

**Opt-in bounded triage** of the full test suite. The command **diagnoses** failures and
**proposes** fixes — but **does not apply them itself**. Applying any fix requires
explicit human approval (`human-approves-any-fix`).

> **OPT-IN — does not run automatically.** This command runs **only** when
> the user explicitly invokes `/dev:test-triage`. It is NOT registered in any
> Claude Code hook, cron/scheduled agent, or `settings.json`. "Nightly triage" =
> a human runs it before leaving / at the start of the day, not a harness on a timer. This is
> a deliberate constraint (ROADMAP § E.4 "Ralph rejected"): bounded autonomy, human
> owns anything irreversible.

Argument: $ARGUMENTS — optional subset (`tests/unit`, a path, `-k <expr>`). Empty = the whole suite.

## Hard caps

A single `/dev:test-triage` run is bounded — **whichever comes first**:

- **≤ 3 iterations** of diagnosis (re-run suite + diagnose). The counter is tracked in the prose report.
- **≤ 50k tokens** for the whole run. The budget is read from the same telemetry as `/dev:pipeline`
  (`data/pipeline-metrics.jsonl`, Stop-hook `token-budget-meter`). Exceeding it → **STOP**,
  output a partial report tagged `BUDGET-EXCEEDED`.

The caps exist so an opt-in nightly run doesn't turn into an unbounded loop.
**This is not an autonomous runner** — `ai-judge` owns the stop-condition, the command doesn't "spin".

## Cycle (≤ 3 iterations)

**1. Run** — run the suite, capturing output to a file:
`uv run pytest $ARGUMENTS -v 2>&1 | tee /tmp/triage_out.txt`
(no `uv` → `pytest`; scoped, not bare from the root — see `_stack.md`).
- All green → **STOP**, `VERDICT: GREEN`, report "nothing to triage." This is success, not a no-op.

**2. callable gate (deterministic)** — `uv run --no-project python scripts/red_gate.py --report /tmp/triage_out.txt`.
This is the same parser as in `/dev:pipeline` §3 (S3 RED-block), reused as a signal that
"the failures are real, not a broken setup":
- `FAILED` + `AssertionError`/`NotImplementedError` → real failures, something to diagnose.
- `ImportError`/`SyntaxError`/collection-error → **setup/environment** is broken, not the code under test →
  fix the setup (env, imports), this is **not** bug triage. Non-standard output the parser doesn't classify →
  escalate to **ai-judge** (S3 semantics).

**3. ai-judge gate (stop-condition owner)** — launch the **ai-judge** agent (Opus, fresh context)
with the machine signal = the current iteration's `/tmp/triage_out.txt` + a short diff against the
previous iteration's failure set (test names). The judge answers with one verdict:
- `VERDICT: PASS` → the failure set **has changed / there is a new actionable signal** (e.g.,
  a human-applied fix shifted the picture, or a flaky test needs confirming with one more run) →
  the next iteration is allowed.
- `VERDICT: BLOCK` → **no progress** (the same failure set repeats) or the signal is insufficient →
  **STOP the cycle**, move to the report. This is exactly what guards against unbounded triage.

ai-judge is the **bounded owner** of the stop-condition (see `agents/ai-judge.md`): one signal → one verdict,
it does not fix code and does not "drive" the cycle itself.

**4. Diagnose (read-only)** — for each failure cluster, launch the **debugger** agent (Sonnet)
in diagnostic mode: reproduce → root cause → **propose** a fix (a diff sketch, 1-5 lines).
- debugger **does not commit or apply** the fix in this flow — it produces a diagnosis + proposal.
- Multiple independent clusters → can run in parallel (one debugger per cluster).

**5. Human gate (human-approves-any-fix)** — assemble the proposals into a report and **stop the cycle for
a human decision**. The command itself **does not apply** the fix. The human chooses and applies the approved
fix as a separate step — via `/dev:debug` (diagnosis with the fix in scope) or `/dev:tdd`
(failing test → fix), now under human control. After the fix is applied, `/dev:test-triage`
can be invoked again — it starts with a fresh iteration counter.

The iteration increments the counter. On the 3rd iteration (or on `BUDGET-EXCEEDED`) — **STOP** regardless
of the judge's verdict, flagged in the report.

## Report

At the end, output a compact summary:
- `VERDICT`: `GREEN` / `TRIAGED` (proposals exist, awaiting approval) / `BLOCKED` (ai-judge: no progress) /
  `BUDGET-EXCEEDED`.
- Iterations spent: `N/3`. Tokens: `~K/50k`.
- Failure clusters: test(s) → root cause → proposed fix (not applied).
- Next step for the human: which `/dev:debug` / `/dev:tdd` to run on the approved fix.

## When to call

- Failures piled up between sessions — needs a systematic breakdown without an immediate fix.
- Suspected flakiness — a couple of bounded runs under `ai-judge` supervision separates flaky from real.
- Start of day: a quick triage of "what broke overnight" with proposals, but no auto-fix.

## When NOT to call

- One known failure with an obvious cause → go straight to `/dev:debug` (no bounded cycle needed).
- Feature implementation / a new unit → `/dev:tdd` or `/dev:implement` (this is not triage).
- Need a full feature loop with review and ship → `/dev:pipeline`.
- Wanting "let it fix itself until it's green" — **deliberately not supported** (human-approves-fix).

Suite subset / focus: $ARGUMENTS
