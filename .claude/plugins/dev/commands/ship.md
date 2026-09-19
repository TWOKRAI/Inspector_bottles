---
description: Final check before merge/push — tests + linter + review of the changes
disable-model-invocation: true
---

Run the final check before shipping the code:

1. **Quality gate:**
   ```bash
   make gate        # if there is a Makefile (lint + types + tests)
   ```
   Fallback (if make is unavailable):
   ```bash
   uv run ruff check .
   uv run pyright src   # same scope as CI; bare `pyright` pulls in tests/, where type debt usually piles up
   uv run pytest -q
   ```

2. **Change summary:**
   ```bash
   git diff --stat
   git log --oneline -5
   ```
   - **Test discipline:** if the diff changed behavior (not just docs/mechanics) —
     `tests changed → injection performed or skip recorded in plan+commit`: either
     an independent test was written and the reviewer ran a break-injection, or the
     test skip is explicitly recorded in the plan AND in the commit body. Neither one —
     **do not ship**, go back to tester/reviewer.
   - **Injection record (Task 6.2):** if the branch changed `tests/**` — its plan
     must contain a **filled-in** `property | predicted red | observed red` row
     (the "Injections" section in the plan or `plans/<slug>/injections.md`). The table
     header, the `|---|` separator, and the `<placeholder>` from `PLAN.template.md`
     do not count as a record. A non-zero exit from the block below — **STOP**, do not
     ship. This block matches word for word the block in the installed pre-push hook
     (`install_pre_push_hook.sh`); byte-identity is enforced by
     `tests/unit/test_injections_gate.py` — edit both or neither.

```bash
# --- injections-record gate (Task 6.2) --------------------------------------
# The branch changed tests/** → its plan must carry a filled-in row
# `property | predicted red | observed red`. The logic lives in one place,
# scripts/validate_commit/check_injections.py, so pre-push and /dev:ship cannot
# disagree on what counts as a record. This block only locates the script and
# an interpreter; if either is missing, the gate says so out loud instead of
# silently letting the push through.
_repo_root="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
_inj_check=""
for _cand in "$_repo_root"/scripts/validate_commit/check_injections.py \
             "$_repo_root"/src/*/template/plugins/lang-python/templates/validate_commit/check_injections.py; do
  if [ -f "$_cand" ]; then _inj_check="$_cand"; break; fi
done
_inj_py=""
for _cand in "${CLAUDE_PYTHON_BIN:-}" python3 python py; do
  [ -n "$_cand" ] || continue
  if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c "import sys" >/dev/null 2>&1; then
    _inj_py="$_cand"; break
  fi
done
if [ -z "$_inj_check" ]; then
  echo "WARN: injections-record gate skipped — check_injections.py not found (scripts/validate_commit/)" >&2
elif [ -z "$_inj_py" ]; then
  echo "WARN: injections-record gate skipped — no working Python on PATH" >&2
elif ! "$_inj_py" "$_inj_check"; then
  exit 1
fi
# --- end injections-record gate ---------------------------------------------
```

3. **Refs-trace check (plan-driven workflow):**
   - Determine the current branch: `git branch --show-current`
   - Extract the slug from the branch name (everything after `feat/`, `fix/`, `refactor/`, `docs/`, etc.)
   - Find the plan file (new convention — date in the name):
     - Single plan: `ls plans/*_<slug>.md` (format `plans/YYYY-MM-DD_<slug>.md`)
     - Multi-phase: `ls -d plans/*_<slug>` (folder `plans/YYYY-MM-DD_<slug>/`)
   - If the plan is found — **plan→commit enforcement (Phase 1.6): BLOCK ship** if even
     one commit in `main..HEAD` lacks `Refs:` (previously this was only a warning). Check
     each commit, not an aggregate `--grep` (it stays green even when only one commit
     has Refs):
     ```bash
     missing=$(git log --format='%H %s' main..HEAD | while read -r sha subj; do
       git log -1 --format=%B "$sha" | grep -q '^Refs:' || echo "  ✗ $sha $subj"
     done)
     if [ -n "$missing" ]; then
       echo "STOP: commits without Refs: to the plan — add Refs (rebase/amend) before ship:"
       echo "$missing"
       exit 1
     fi
     ```
     - Read the plan (single `plan.md` or metaplan + phase-N.md) and check: if every Task = [DONE] → propose closing the plan (Status: DONE)
   - If no plan is found (legacy branch, hotfix, old convention without a date) — skip, don't block (no plan = no Refs requirement)

4. **Result:**
   - If everything is green — propose a commit message in the correct format
     (see below) and ask permission to push
   - If there are errors — show them and propose a fix
   - **Phase gates are not waived by transport:** phase closed → `cto` acceptance (S7);
     merge into `main` → `cto` merge gate → owner. Rows —
     [`team-protocol`](../skills/team-protocol/SKILL.md) §5. `/dev:ship` is a quality
     gate, not a substitute for these two gates: a green run only lets you **propose**
     a merge, the owner decides after the `cto` verdict.

## Closing the plan + archive (archive-on-done)

If the plan is found and every Task = [DONE] (the remainder is only backlog / a gate for a future release):

1. **Status → DONE** in the plan: `Status: DONE` (single) or every phase `[DONE]` in §2 (multi-phase).
2. **Archive the plan** (it leaves the active set — archive-on-done) — with one command:
   ```bash
   python3 scripts/plans_ledger.py close <YYYY-MM-DD_slug>.md   # single
   python3 scripts/plans_ledger.py close <YYYY-MM-DD_slug>      # multi-phase
   ```
   The script does a `git mv` into `plans/_archive/<YYYY-Qn>/` (quarter — from the date
   in the name), moves the ledger row in `plans/README.md` to "Archive" with status
   `ARCHIVED`, appends to `plans/_archive/<YYYY-Qn>/README.md`, and prints the diff. It
   **refuses** to close a plan with open tasks (rc=1) — that's exactly the "every
   Task = [DONE]" check (a task marked `[SKIPPED]`/`[CANCELLED]` doesn't block this).
   `plans_ledger.py close` writes `SUMMARY.md` into the plan directory before the move;
   a new session reads an archived plan through its `SUMMARY.md` only.
3. **Refresh, then check the ledger:** `python3 scripts/plans_ledger.py add <plan-dir-or-file relative to plans/>`, then `python3 scripts/plans_ledger.py status` — no findings for the closed plan
   (show other `WARN`s to the owner, but don't fix them silently).
4. Commit:
   ```bash
   git add plans/
   git commit -m "docs(plans): архив <slug> (план выполнен)

   Why: все задачи плана выполнены → archive-on-done
   Layer: docs
   Refs: plans/_archive/<YYYY-Qn>/<slug>(.md|/plan.md)"   # drop Layer if commit-layers.txt is empty
   ```

**NEVER** delete a plan (`Refs:` history depends on it), and **do NOT** archive a plan
with open items — keep it in "Active" (`plans/README.md`) with a note of what remains.

## Commit message format

**Canonical guide:** [`.claude/COMMIT_GUIDE.md`](../../COMMIT_GUIDE.md) — full format, types, trailers, examples.
**Project settings:** [`.claude/modes/_stack.md`](../../.claude/modes/_stack.md) (validator on/off) + [`.claude/commit-layers.txt`](../../.claude/commit-layers.txt) (if the file is empty → `Layer:` is optional).

The `commit-msg` hook rejects an incorrect format (if installed). Before committing you can run validation manually:

```bash
echo "<full message>" | python3 scripts/validate_commit/validate_commit.py -
```

$ARGUMENTS
