---
name: git-stash-pop-grabs-unrelated-stash
description: verifying pre-existing failures via stash+checkout can pop an UNRELATED pre-existing stash and pollute the tree with conflict markers
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7e9a7cc4-c9bd-4c06-b1fc-c94b66b87684
---

To check whether test failures are pre-existing, I did `git stash -u` → `git checkout <base>` → run → `git checkout <branch>` → `git stash pop`. On a CLEAN tree `git stash -u` stashes NOTHING, so the later `git stash pop` popped a pre-existing UNRELATED stash (`f2.2-wip` from another branch), which conflicted → `<<<<<<< Updated upstream` markers landed in process_module/health, generic/*, test_health_live.py (files unrelated to my task). Surfaced only when pytest hit a SyntaxError on the conflict marker.

**Why:** `git stash pop` always targets `stash@{0}` — not "the stash I just made". If my stash was a no-op, pop grabs whatever was already on the stack.

**How to apply:** To confirm pre-existing failures, use an isolation:worktree agent or a throwaway `git worktree add` at the base SHA — NEVER stash+checkout on the working branch. If stash is unavoidable: `git stash list` FIRST; only pop by explicit ref you just pushed (`git stash pop stash@{0}` only after confirming it's yours); after any pop, `grep -rl '<<<<<<< '` before trusting the tree. Recovery: `git checkout HEAD -- <polluted files>`, `rm` untracked stash additions, leave the foreign stash entry intact (a conflicted pop does not drop it). Related: [[feedback_git_main_merge_hook_traps]], [[feedback_worktree_stale_base]].
