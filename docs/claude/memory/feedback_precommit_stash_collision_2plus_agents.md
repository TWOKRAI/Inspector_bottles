---
name: feedback-precommit-stash-collision-2plus-agents
description: pre-commit's staged_files_only isolation (its own patch-based stash, not git stash) collides when 2+ agents commit concurrently in the same non-worktree checkout — reverts unrelated unstaged files tree-wide, blast radius grows with each retry
metadata:
  type: feedback
---

Observed independently by two agents on the same day (branch `fix/backend-ctl-hardening`,
2026-07-20): pre-commit's `staged_files_only` isolation snapshots *all* unstaged changes
tree-wide into a patch file before running hooks, then tries to `git apply` that patch
back afterward. When a second agent commits concurrently in the same working tree (no
`git worktree` isolation — see `feedback_git_stash_pop_wrong_stash.md` for a related but
distinct stash-based collision), a shared file the hooks touch on every commit
(`docs/sessions/<date>.md`, written by an "append session log" hook) has usually moved
by the time the patch tries to re-apply, so `git apply` aborts and pre-commit fails the
whole commit — leaving the patch orphaned in `~/.cache/pre-commit/patch<N>` and the
working tree reverted to a stale state for **every** file that was unstaged at stash
time, not just the colliding one.

Retrying blindly makes it worse: each retry re-snapshots whatever is unstaged *right
then* (including the other agent's freshly-reverted files), so the blast radius grows
across attempts — one incident escalated from 2 files to 9+ files across two agents'
work over 8 retries, including files neither agent's own commit even referenced.

**Why:** the project's shared pre-commit hooks (ruff-format auto-fix + append-session-log)
write to files tree-wide on every commit; under 2+ agents in one checkout this makes the
race near-certain, not theoretical.

**How to apply:**
- Prefer `git worktree` per concurrent agent (see the project's existing
  `feedback_worktree_for_parallel_samefile` guidance) — this failure mode doesn't occur
  across separate worktrees.
- If stuck without worktree isolation: cap retries at 2-3. After that, stop and escalate
  — do not keep retrying hoping the other agent finishes first.
- Recovery for files with a *staged* (index) copy that reverted in the working tree:
  `git show :path/to/file > path/to/file` restores the last-known-good content without
  invoking `git checkout`/`git restore` (both may be blocked by permission settings).
  Files that were only ever unstaged (never staged) have no safe recovery source — leave
  them for their owning agent, don't guess.
- Before assuming a commit landed, verify: `git log --oneline -3` + `git status --short`.
  "Commit failed" after this failure mode means "re-verify everything in the tree," not
  "nothing changed" — collateral files can revert even though your own commit never ran.

**Refined 2026-09-08 (three failed commits in a row, then reproduced and fixed).** The collision
does NOT need a second agent to be committing at the same time, and `git diff --name-only` being
empty proves nothing. `git commit -- <pathspec>` builds a TEMPORARY index from HEAD plus the
pathspec files; pre-commit computes "unstaged" against that temporary index, so any file that is
staged in the real index but outside the pathspec (here `docs/sessions/<date>.md`, staged by a
neighbour's earlier attempt) shows up as an unstaged diff, gets stashed, the session-log hook
appends to that same file, and the stash fails to re-apply at the hook's insertion point. Fix that
worked: bring the session file to HEAD in both tree and index (`git show HEAD:path > path && git add path`),
commit with the pathspec, then realign the index to the new HEAD the same way. The 19 dropped lines
were the hook's own record of a failed attempt — worthless, but keep a copy before dropping.
Line endings (CRLF in tree vs LF in index) were the wrong hypothesis; ruled out by the
`autocrlf=false` diff being empty and the fourth failure. See also
[[feedback_a_hook_that_writes_a_shared_file_deadlocks_two_writers]].
