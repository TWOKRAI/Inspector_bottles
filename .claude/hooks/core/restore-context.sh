#!/usr/bin/env bash
# PostCompact hook — restore critical context after compaction.
# Without this Claude forgets key rules during long sessions.
#
# This hook is intentionally generic — project-specific rules live in
# CLAUDE.md / .claude/CLAUDE.md / .claude/modes/_stack.md, which the agent
# re-reads after compaction. The block below re-anchors the navigation
# map and the commit format only.

cat <<'CONTEXT'
## Restored context (PostCompact)

**Navigation (re-read if unsure):**
- `.claude/CLAUDE.md` → "Project layout" table + "Memory (OVERRIDE)" rules
- `.claude/modes/_stack.md` → stack, layers, commit-format toggle for this project
- `CLAUDE.md` (project root) → goals, architecture, key paths

**Plan ↔ branch ↔ commit ↔ session thread:**
1. `plans/<slug>.md` lives under the current branch's slug (`<type>/<slug>`).
2. Commits MUST trail `Refs: plans/<slug>.md` when a plan exists for the branch.
3. Commit format: `<type>(<scope>): subject` + `Why:` (required) + `Layer:` (required if `.claude/commit-layers.txt` is non-empty). Hook: `scripts/validate_commit/validate_commit.py`.
4. Session journal: `docs/sessions/YYYY-MM-DD.md` (via `/wrap-up`).
5. Long-term memory: `.claude/memory/MEMORY.md` (per "auto memory" rules).

**Safety:**
- Never `git push --force`, `git reset --hard`, or `--no-verify` (except merge/rebase).
- Confirm before destructive ops; investigate unknown state before deleting.
CONTEXT
