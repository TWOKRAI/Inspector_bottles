---
name: feedback-worktree-base-drift
description: Agent worktrees can lag many commits behind main — verify base freshness before trusting referenced plan/review docs or building on "existing" code.
metadata:
  type: feedback
---

Before starting a task that references specific plan/review docs (e.g. `plans/<slug>/plan.md`,
`review-*.md`) or claims specific code/ADR state already exists, check that the worktree HEAD
is actually caught up to the referenced state — do not assume a worktree assigned for a task is
fresh.

**Why:** Hit this on task NEW-3 (2026-07-11): worktree `agent-a5b6f0455fc2f7a3b` was checked out
at `a50d1f74`, 76 commits behind `main` (`32c54a34`). The referenced `plans/current-path/plan.md`
and `review-2026-07-11.md` didn't exist in the worktree at all (only in the separate main repo
checkout) even though the task brief assumed they were readable in-place. The underlying code
(`message_module/contracts`, `command_contracts.py`) happened to be unaffected by the 76-commit
gap in this specific case, but that was luck, not something to assume next time — the coordinator
had to interrupt mid-task with a correction once it noticed the drift.

**How to apply:** Early in a task, if a referenced doc path 404s in the assigned worktree but the
task describes it as existing, that's the tell — don't quietly fall back to reading it from
elsewhere and proceed unquestioned. Run `git merge-base --is-ancestor <worktree-HEAD> main` and
`git rev-list --count <worktree-HEAD>..main` to quantify drift. If significant and the task
touches code that could plausibly have changed upstream, rebase/re-checkout onto the fresh base
(`git checkout -B <branch> <fresh-main-sha>`) BEFORE writing any implementation, then diff the
specific files/directories you're about to touch between old and new base to confirm your
analysis still holds (don't blindly re-trust earlier reads). Stash any WIP first (`git stash
push -u`) — it reapplies cleanly across a fast-forward-only gap if the touched files didn't
actually change upstream.
