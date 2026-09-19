---
description: Implement one Task per spec with contract-first TDD by default (interface → red → green)
---

Implement **one** Task X.Y from the plan (or from $ARGUMENTS) following **contract-first TDD**
discipline. This is a standalone variant of the implementation step from `/dev:pipeline` §2 —
without planning (manager), the full regression run, or the review loop. For the full cycle use
`/dev:pipeline`.

Pass agents ONLY the specific Task (not the whole plan), exact file paths, and acceptance criteria.
If the task depends on a previous one — make sure that one is done.

## 1. Determine the task contract (stage fork)

Read the **`Module contract:`** field from the Task spec (set by `manager` — see
`agents/manager.md` → "Module contract"). It determines the fork:

| Module contract | Implementation stages |
|---|---|
| `new-full` / `new-lite` | **INTERFACE → RED → GREEN → [REFACTOR]** |
| `public-api-change` | **INTERFACE (edit) → RED → GREEN → [REFACTOR]** |
| `impl-only` | **RED → GREEN → [REFACTOR]** (interface untouched) |
| `n/a` | direct implementation (config / docs / dep-bump — TDD not applicable) |

If the field is missing (legacy plan, manual $ARGUMENTS) — **determine the branch yourself** based
on the nature of the task (new public module → `new-*`; edit to `interface.py` / `__init__.py` →
`public-api-change`; internal fix with no API change → `impl-only`; non-module change → `n/a`) and
**report the chosen branch to the user** before starting.

**The canonical algorithm for each stage** (Pre/Post, anti-cheat rationale, exact commit messages,
failure-recovery) — `/dev:pipeline` §2 (single source of truth). This is the same contract→stage
table; below is the orchestration for standalone mode.

## 2. Stages (per the chosen branch)

**The brief for each executor:**
- **Plan layout v2** (`tasks/<id>.md` exists under the plan directory): run
  `python3 scripts/plans_ledger.py brief <id>` (add `--plan <path>` when more
  than one plan is active). Its stdout IS the spawn prompt — pass it
  VERBATIM to the executor, plus this transport's own lines (worktree path,
  peers). To change the brief, edit `tasks/<id>.md` and re-run; never
  hand-edit the printed text. A refusal (`BriefRefused`) names the missing
  field(s) — fix `tasks/<id>.md` and re-run; it goes back to the task
  file's author, not around it.
- **No `tasks/` directory** (phase layout or single-file plan): fill the
  form `.claude/plugins/dev/templates/executor-brief.md` by hand — DESIGN
  from the lead (which function, which call site, what not to touch), FILES
  — a numbered list of allowed files, REDS — ≤ 10 predicted reds, first
  edit within the first 5 calls, TESTS — only the task radius, in the
  foreground (`timeout: 300000`, never in the background).

Nothing to fill DESIGN with → `investigator` or a lead decision first, not
the writer. While the agent works — watch
`uv run --no-project python scripts/agent_report.py --live`, don't correspond with it (the three stop rules are in the
form).

**INTERFACE** (only `new-*` / `public-api-change`) — launch **developer** (Sonnet) or
**teamlead** (Opus, if Senior+ level) with the `module-contract` skill active: formal
contract-in-code FIRST (`interface.py` for full / module docstring for lite — `Protocol`/`ABC`
+ `Pre:`/`Post:`/`Invariants:` on every public function), module README **without** Usage examples
(examples = contract tests from RED). No implementation yet (`_impl/` empty or `raise NotImplementedError`).
Commit: `feat(<scope>): interface for Task X.Y` + `Refs:`.

**RED** — launch **tester** (Sonnet) in `MODE: red`. Parameters are passed as a header in the
first lines of the prompt (see `agents/tester.md` → "How the orchestrator passes parameters"):
`MODE: red`, `INTERFACE:`, `MODULE_CONTRACT:`, `TASK:`, `PLAN:`. Tester reads **only** the contract
(not `_impl/`), writes one failing test per Pre/Post line, and **demonstrates** the failure with
the right error type (`NotImplementedError`/`AttributeError` for `new-*`; `AssertionError` for
`public-api-change`/`impl-only`). If the test passes → the test is wrong, rewrite it. Commit:
`test(<scope>): failing test for Task X.Y` + `Refs:`.

**GREEN** — launch **developer** (Sonnet) or **teamlead** (Opus, if Senior+):
- Pass the path to `interface.py` (if there was an INTERFACE) **and** the path to the RED test — the agent **reads both**, doesn't guess the contract.
- Goal — the **minimal** implementation in `_impl/` that makes the RED test pass and honors the Pre/Post from the interface. No over-engineering for the future.
- The agent **does not edit** `interface.py` or the RED test. Wrong contract → back to INTERFACE / to `manager` for a spec revision, **not** massaging the test to fit the code.
- Commit: `feat(<scope>): impl for Task X.Y` + `Refs:`. Update the Task status `[PENDING]` → `[DONE]`, then refresh the ledger row: `python3 scripts/plans_ledger.py add <plan-dir-or-file relative to plans/>`. For a plan with `tasks/`, write `tasks/<id>.result.md` (<= 2 KB): the commit SHAs from `git rev-parse`, every acceptance number with the command that produced it, deviations from DESIGN — nothing else.

**REFACTOR** (optional) — if GREEN left obvious debt: `developer` cleans up in the same context, tests stay green after every edit, `interface.py` is untouched (an API change goes through a separate `public-api-change` Task).

For the `n/a` branch — the stages above don't apply: implement directly (developer/teamlead per level), one commit with `Refs:`.

## 3. Refs tracing (plan-driven workflow)

- Determine the plan file path: from $ARGUMENTS or from the current branch (`git branch --show-current` → extract the slug → find it in `plans/`):
  - Single plan: `plans/YYYY-MM-DD_<slug>.md` (find via `ls plans/*_<slug>.md`)
  - Multi-phase: `plans/YYYY-MM-DD_<slug>/plan.md` + `phase-N.md` (find via `ls -d plans/*_<slug>`)
- Every stage commit — with trailer `Refs: <path-to-plan-file>` (exact path, with the date).
  Examples: `Refs: plans/2026-05-22_auth-rbac.md` or `Refs: plans/2026-05-22_auth-rbac/phase-2.md`.
- For multi-phase plans: link to the specific phase file (not the `plan.md` metaplan, not the folder).
- If the plan isn't found (legacy branch, hotfix, undated plan file) — warn the user, but don't block the work.

## 4. After completion

- Verify that **every** stage commit carries the `Refs:` trailer and the Task status in the plan is updated `[PENDING]` → `[DONE]`, then refresh the ledger row: `python3 scripts/plans_ledger.py add <plan-dir-or-file relative to plans/>`. For a plan with `tasks/`, write `tasks/<id>.result.md` (<= 2 KB): the commit SHAs from `git rev-parse`, every acceptance number with the command that produced it, deviations from DESIGN — nothing else.
- developer commits on its own; in the subagent brief repeat: never push, never open a PR.
- Remind about the regression run (`/dev:test` in `MODE: regression`) and review (`/dev:review`) — in standalone they don't run automatically (that's `/dev:pipeline`'s job).

Task: $ARGUMENTS
