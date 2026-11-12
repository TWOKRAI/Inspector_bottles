---
name: coordinator-status-from-main-not-order
description: "Coordinator must take task status from git main, never from ORDER.md or the checked-out tree; write only via a worktree off main"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 2788941e-43ef-4698-9fa1-3cca00d1f88f
  modified: 2026-11-11T18:10:55.095Z
---

ORDER.md lags git: on 2026-11-11 its rows 7, 8, 9 (T5.3e.5, T1.4, T5.5) and row 3 (R1/C-30) were already merged in `main`; advice built on the file ("lane D: R1") was wrong and had to be retracted.
The primary checkout may also sit on another lane's branch (here the Atlas branch with uncommitted queue edits), so files read there are not `main`.

**Why:** a wrong status gives the owner a wrong recommendation and burns a lane's start prompt.
**How to apply:** before recommending or writing a prompt, check `git merge-base --is-ancestor <branch> main`, `git log main --grep=<id>`, `git show main:<path>`; delegate the inventory to an Explore/haiku agent with "read only from main". Read from a local merge branch (`coord/main-plus-atlas`) when both lines are needed; write only through a worktree cut from `main` (`git worktree add -b <branch> <path> main`), merge with `git merge --no-ff -F <file>`; check `git branch --show-current` before any commit. Related: [[primary-tree-may-sit-on-another-branch]].
