---
description: Show task completion progress of the current plan. Call to see what is done and what is next.
---

Show progress across plans:

0. **Ledger (overview without rereading every plan):**
   ```bash
   python3 scripts/plans_ledger.py status          # human-readable
   python3 scripts/plans_ledger.py status --json   # for parsing
   ```
   The script cross-checks the "Active" / "Archive" tables in `plans/README.md` against the
   plan files: task count `N/M` and phase are computed from `### Task` (closed — all
   checkboxes marked, or `[DONE]` in "Execution order"), plus the findings
   `DONE_NOT_ARCHIVED` / `MISSING_ROW` / `ROW_WITHOUT_FILE`. For a general "what's still
   open" this is enough — don't read every plan. `python3 scripts/plans_ledger.py add <plan>`
   refreshes a row; verify `DONE` status against git (`git merge-base --is-ancestor <branch>
   main`), not against checkmarks.

   `python3 scripts/plans_ledger.py summary <plan>` previews the one-page
   `SUMMARY.md` a `close` would write (Goal/Tasks/Amendments/Open->backlog).
   An **archived** plan is read through its `SUMMARY.md`, never by opening
   the archived directory. The ledger's `tasks` column counts `done/total`;
   a task marked `[SKIPPED]`/`[CANCELLED]` counts as dropped, not open —
   `close` succeeds once every remaining task is done or dropped, without
   `--force`.

   If `scripts/plans_progress/plans_progress.py` exists and `plans/queue/progress-baseline.txt` exists (otherwise skip this
   step without error), progress by the
   plan-format standard (one scale `N of M` per plan, findings) comes from it; the check is the one `/dev:ship`
   runs, the page is for reading:
   ```bash
   python3 scripts/plans_progress/plans_progress.py --check --baseline plans/queue/progress-baseline.txt
   python3 scripts/plans_progress/plans_progress.py --html data/plans_progress.html   # page: --html
   ```
   Exit 1 of `--check` = a new blocking finding outside `plans/queue/progress-baseline.txt`.

1. **Current branch:**
   ```bash
   git branch --show-current
   ```
   Extract the slug from the branch name (everything after `feat/`, `fix/`, `refactor/`,
   `docs/`, etc).

2. **Find the plan:**
   - Check `plans/<slug>.md` and `plans/<slug>/plan.md`
   - If not found — fallback: search `Refs:` in the current branch's commits:
     ```bash
     git log main..HEAD --format=%B | grep -oE "Refs: [^[:space:]]+" | sed 's/^Refs: //'
     ```
   - If still not found — show the list of all files in `plans/`

3. **For the found plan:**
   - Read the file(s)
   - Count tasks by status: `[PENDING]`, `[IN_PROGRESS]`, `[DONE]`
   - Show the frontmatter (Slug, Date, Status, Branch)

4. **Output format:**
   ```
   ## Plan: <title>
   **Slug:** <slug>  |  **Branch:** <branch>  |  **Status:** IN_PROGRESS
   **Progress:** ████████░░ 8/10 tasks (80%)

   ### Phase 1: <name> ✅
   - [DONE] Task 1.1: ...
   - [DONE] Task 1.2: ...

   ### Phase 2: <name> 🔄
   - [DONE] Task 2.1: ...
   - [PENDING] Task 2.2: ...
   ```

5. **If no plan is linked:** show the active plans from
   `python3 scripts/plans_ledger.py status` (rather than a raw `ls plans/`):
   ```
   ⚠️ No plan linked to branch `<branch>` (normal for hotfix/experiment).
   Active plans (from plans/README.md):
   - 2026-05-01_auth-rbac.md — IN_PROGRESS — remaining: RBAC tests
   - 2026-05-03_graph-validation.md — DRAFT
   ```

If $ARGUMENTS contains a specific slug or path — show that one.
If empty — show the plan for the current branch.

$ARGUMENTS
