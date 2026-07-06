---
description: Run the reviewer eval — grade the code-reviewer agent's output against golden cases (offline deterministic floor; LLM-judge deferred).
---

Run the reviewer golden-task eval. The harness lives at
`.claude/plugins/dev/evals/run_evals.py` (stdlib-only on the default path — no API
key, no network). It grades the **outcome** of a review (the findings set + verdict),
not the trajectory.

Argument: $ARGUMENTS (the suite name, e.g. `reviewer`; defaults to `reviewer`).

## Usage

Run via Bash (the harness is a stdlib Python script):

- Suite run — grade the committed reviewer outputs against the golden corpus and
  report pass-rate + Wilson CI:
  `python .claude/plugins/dev/evals/run_evals.py`
- Validate the corpus — offline schema + self-consistency check (also runs in CI on
  every PR, no key needed):
  `python .claude/plugins/dev/evals/run_evals.py --validate-cases`
- Grade one captured reviewer output against a case:
  `python .claude/plugins/dev/evals/run_evals.py --output <file> --case cr-001`

## What it reports

Per case: recall of planted defects (the most-penalised axis — a missed bug is the
worst failure), precision against labelled `must_not_flag` decoys, the verdict
(`APPROVED` / `CHANGES_REQUESTED` / `ESCALATION`), and format/boundary conformance. A
case passes the deterministic floor only when it catches every planted defect, flags
no decoy, returns the right verdict, and stays in role (no code patch, no git op).
Headline metric for a consistency-critical reviewer is **pass^k** (caught the bug in
every run), not pass@k.

## Scope (offline floor, v1)

The default path is fully deterministic and offline. Two layers are scaffolded behind
flags and deferred to a follow-up (they need an `ANTHROPIC_API_KEY` and run nightly,
never per-PR):

- `--invoke` — live-invoke the reviewer via headless `claude -p` per case.
- `--judge` — add per-dimension LLM-judge scores (`claude-opus-4-8`, temperature 0,
  one isolated judge per rubric in `dev/evals/reviewer/rubrics/`; ambiguous 0.4–0.6
  scores route to a human-review queue).

Both currently exit with a "deferred" message. See `dev/evals/README.md` for the
full design, the case-authoring guide, and how to add cases toward the 20–50 target.

After running, read the actual reviewer outputs before trusting the aggregate — a
green score can still hide reward-hacking or a lucky trial.
