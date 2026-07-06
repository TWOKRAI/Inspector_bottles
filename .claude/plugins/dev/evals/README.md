# dev evals — golden-task harness for the code reviewer

Behavioral evals for the dev-plugin **reviewer** agent. Given a corpus of golden
diffs sourced from real review failures, this harness grades the reviewer's *output*
(the findings set + verdict) against a labelled ground truth — **the result, not the
trajectory**. It does not assert how the reviewer read files or which tools it called.

> **Status: offline-floor v1.** The deterministic grader is fully stdlib and offline
> (no API key, runs per-PR). The LLM-judge and live `claude -p` invocation are
> scaffolded behind `--judge` / `--invoke` and deferred to a follow-up (see
> [Deferred layers](#deferred-layers)).

Pattern source: Anthropic, *Demystifying evals for AI agents* — grade the outcome;
ship a reference solution per case to prove the bug is catchable; headline metric is
**pass^k** for a consistency-critical reviewer; route ambiguous judge scores to a
human queue; never trust the aggregate without reading transcripts.

## Layout

```
dev/evals/
├── run_evals.py            # the harness (stdlib-only default path)
├── grader_stats.py         # Wilson CI + finding-match precision/recall/F1
└── reviewer/
    ├── cases/cr-NNN.json   # one self-describing golden task per file
    ├── fixtures/cr-NNN/
    │   ├── diff.patch          # the code change under review (the "environment")
    │   └── reference_review.md # reference solution — proves the bug is catchable
    │                           #   and that the graders fire on a known-good output
    │   └── captured_review.md  # (optional) a real reviewer output to grade in CI
    └── rubrics/*.md        # per-dimension LLM-judge rubrics (deferred path)
```

The whole eval feature is **plugin-only** dev-tooling — `evals/` and the `/dev:eval`
command both live only in the canonical plugin tree, not in the legacy
`src/claude_kit/template` flat mirror (same accepted precedent as the other
dev-tooling exclusions). They ship to plugin-based projects (the canonical path) but
are not carried by engine self-migration into legacy-bootstrapped projects. The only
mirrored change is the reviewer agent's "Severity scale" section.

## Running

```bash
# Validate the corpus (schema + self-consistency). Runs in CI per PR; no key.
python run_evals.py --validate-cases

# Suite run: grade the committed outputs (captured_review.md, else reference_review.md).
python run_evals.py

# Grade one captured reviewer output against a case.
python run_evals.py --output some_review.md --case cr-001
```

Exit codes: `0` pass / valid, `1` failures, `2` warnings under `--strict`.

## Case format

One case = one `cr-NNN.json` + a `fixtures/cr-NNN/` dir. Fields:

| Field | Meaning |
|-------|---------|
| `id` | `cr-NNN` (unique, stable — case ids are a contract; renaming drops the case from regression comparison). |
| `category` | `missed_bug` \| `false_positive_resistance` \| `severity_grading` \| `clean_diff` \| `escalation`. |
| `source` | Provenance — which real failure this was distilled from. Synthetic-only suites drift from reality. |
| `diff_path` | The unified diff under review (relative to `reviewer/`). |
| `prompt` | The instruction handed to the reviewer, including acceptance criteria. |
| `ground_truth.must_find` | Planted defects: `{file, line, category, severity, cwe?}`. recall is graded against these. |
| `ground_truth.must_not_flag` | Decoys: `{file, line?, reason}` — correct/intentional patterns. Flagging one is a false positive. |
| `expected_verdict` | `APPROVED` \| `CHANGES_REQUESTED` \| `ESCALATION`. |
| `graders` | Which checks apply (deterministic always; `llm_judge` dims are deferred). |
| `reference_review_path` | A known-good review in the exact reviewer output format. |

`category` / `severity` use the reviewer's own taxonomy. Severity scale (single source
of truth in `dev/agents/reviewer.md` → "Severity scale"): **blocker** = security,
spec; **major** = architecture, IPC, UI, tests; **minor** = quality.

**Invariant (Anthropic):** a good case is one where two domain experts would
independently reach the same verdict. `--validate-cases` enforces a weaker, automatic
version: each `reference_review.md`, graded against its own case, must score a perfect
floor (recall 1.0, no decoy hit, verdict match) — proving the planted bug is catchable
and the graders fire.

## Grading — two tiers

1. **Deterministic floor (always on, offline).** Parse the reviewer output into
   findings (regex on the `[file:line] [category] — Problem: … Fix: …` format from
   `reviewer.md`) and a verdict, then:
   - **recall** = planted defects matched / total (matched by `{file, line ±window,
     category}`). A missed defect is the most-penalised failure.
   - **precision** = true findings / (true findings + decoy hits) — measured only
     against labelled `must_not_flag` decoys, never against "any extra finding".
   - **verdict match**, **format conformance** (category in the closed 7-enum, every
     finding has file+line+Problem+Fix), **boundary discipline** (no code patch, no
     git op, correct `ESCALATION` on the 3rd iteration).
   - A trial passes only if recall is 1.0, zero decoy hits, verdict correct, format
     valid, and boundary intact.
2. **LLM-judge (deferred).** One isolated judge per subjective dimension
   (`rubrics/{signal_noise,severity,thoroughness,boundary_discipline}.md`), temperature
   0, with an explicit *Unknown* escape hatch. Scores 0.4–0.6 go to a human-review
   queue, not a binary.

Aggregate: **pass^k** (passed every one of k trials — the honest metric for a reviewer
you must trust) is the headline; pass@k and mean recall ± Wilson CI are secondary.

## Deferred layers

`--invoke` (live reviewer via `claude -p`) and `--judge` (LLM-judge, `claude-opus-4-8`)
both currently exit with a "deferred" message. Wiring them is the Phase 3.c follow-up:

- Add `ANTHROPIC_API_KEY` as a workflow secret and create
  `.github/workflows/evals-nightly.yml` (`schedule` cron + `workflow_dispatch`) — never
  per-PR (cost + non-determinism). Run small `k` (3–5) and report pass^k + Wilson CI.
- Judge default model `claude-opus-4-8` (same tier as the reviewer under test — no
  silent downgrade; the cheaper `claude-sonnet-5` is an explicit high-volume option).
  Use `messages.count_tokens` for cost estimation, never tiktoken.
- Local Ollama is **not** a viable default judge: the installed models are
  embedding-only (`does not support generate`); a generative model must be pulled
  first. Leave it as a documented `--judge-backend` opt-in.

## Adding cases

Start from a real review miss. Author `cr-NNN.json` + `diff.patch` +
`reference_review.md`, run `--validate-cases` until green, commit. Grow toward 20–50
cases with progressively subtler defects (multi-file, tempting false positives,
inverted severity). When a case sits at 100% pass^k over time it has saturated —
graduate it into a regression-only set and add harder cases to keep an improvement
signal (the eval-saturation trap).
