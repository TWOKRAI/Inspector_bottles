---
description: Opt-in weekly dependency bump — uv lock --upgrade, run the suite, ai-judge gate on green, open a DRAFT PR (human merges). Falls back to gh CLI / stdout diff. Never auto-runs, never merges.
---

**Opt-in weekly dep-bump.** The command updates locked dependencies, runs the tests,
and on a green verdict opens a **draft PR** — but **never merges**. Merging is
the human's decision (`human-merges`).

> **OPT-IN — does not run automatically.** Runs **only** on an explicit call to
> `/dev:dep-bump`. Not registered in any hook, cron, or scheduled agent.
> "Weekly" = a human runs it once a week, not the harness on a timer. Boundary of
> responsibility: **the agent creates a draft PR, the human reviews and merges** (ROADMAP § E.4,
> human owns the irreversible). The command itself never does `git push`/merge into `main`.

Argument: $ARGUMENTS — opt. specific packages (`--upgrade-package <name>`). Empty = full `--upgrade`.

## Cycle

**1. Branch** — branch off a fresh `main`, so the bump doesn't hang on a working branch:
`git checkout main && git pull --ff-only && git checkout -b chore/dep-bump-<YYYY-MM-DD>`.

**2. Upgrade lock** — re-resolve dependencies:
- Full: `uv lock --upgrade`
- Targeted: `uv lock --upgrade-package <name>` (from $ARGUMENTS).
Capture the `uv.lock` diff (`git diff uv.lock`) — this is the machine signal for the judge (what moved where).

**3. Sync + suite** — install the new lock and run the whole suite:
`uv sync && uv run pytest tests/ -q` (scoped, not bare — see `_stack.md`).
Capture the output to a file: `... 2>&1 | tee /tmp/depbump_out.txt`.

**4. ai-judge gate (green tests + no breaking = PASS)** — run the **ai-judge** agent
(Opus, fresh context) with the machine signal = `/tmp/depbump_out.txt` (suite result) +
`git diff uv.lock` (what moved up). The judge issues one verdict:
- `VERDICT: PASS` → suite is green **and** the diff has no risky major jumps without confirmation →
  proceed to the draft PR.
- `VERDICT: BLOCK` → suite is red, or a major bump with a likely breaking change → **STOP**:
  don't create the PR, print a report (what failed / which package is risky). Next — a human:
  roll back the package (`--upgrade-package` targeted) or fix it via `/dev:debug`.

ai-judge here is the bounded owner of the gate decision (see `agents/ai-judge.md`): it judges
the signal (suite + lock-diff), it does not fix dependencies and does not merge.

**5. Commit + draft PR (human-merges)** — only on `VERDICT: PASS`:
- Commit: `chore(deps): weekly dependency bump (uv lock --upgrade)` with a body — the list
  of bumped packages `name old → new` from the `uv.lock` diff.
- Open a **draft** PR into `main` (3-level fallback):
  1. **github MCP** available (`enabled.yaml` → `github`) → create the PR via MCP with the draft flag.
  2. Otherwise **`gh` CLI**: `gh pr create --draft --base main --title "chore(deps): weekly dependency bump" --body <…>`.
  3. **Fallback (neither github MCP nor `gh`)**: do NOT create the PR. Print to stdout:
     `git diff main...HEAD --stat` + the list of bumps + a ready-made instruction:
     "PR not created automatically (github MCP / gh CLI unavailable). Push the branch
     `chore/dep-bump-<date>` and open a draft PR into `main` manually." This is not an error —
     it's a graceful degrade.

The PR is created as **draft** intentionally: the human reviews the changelogs of the bumped
packages and moves it from draft to ready + merges it themselves.

## Report

- `VERDICT`: `PASS` (draft PR #N created / instruction printed) / `BLOCK` (what failed or which package is risky).
- Bumped packages: `name old → new` (flag major jumps specifically).
- Suite: passed/failed.
- Next step for the human: link to the draft PR or the command to push the branch.

## When to call

- Once a week / before a sprint — pull in security patches and minor updates under the suite's protection.
- After a long pause in the project — a one-off controlled bump with a draft PR for review.

## When NOT to call

- Need a specific package for a feature → install it directly (`uv add <pkg>`), this is not a "weekly bump".
- Suite is already red before the bump → first `/dev:test-triage` / `/dev:debug`, don't mask failures with an upgrade.
- Need to merge into `main` immediately without review — **intentionally not supported** (human-merges, draft PR only).

Packages / focus: $ARGUMENTS
