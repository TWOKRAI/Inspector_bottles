---
name: concurrent-agent-writes-outside-git-index
description: another agent in the same non-worktree checkout can write files directly (not just commit) mid-task — scope your final diff by content, not by "everything git status shows"
metadata:
  type: feedback
---

During Task 1.1 of `observability-closure` (2026-08-29), `docs/claude/memory/CRAFT.md` plus two new
`docs/claude/memory/feedback_*.md` files appeared in `git status` mid-session, written by a
concurrent agent (same `originSessionId`, i.e. a parallel subagent in this same top-level session)
documenting reviewer findings for the same plan — not something I wrote. A harness system-reminder
("changed on disk since you last read it") on a file I *did* touch (`test_process_hooks_wiring.py`,
reformatted by `ruff format`) was the honest signal; the memory files had no such reminder and were
only caught by running `git status --short` before the final report.

**Why:** existing memory ([[feedback_parallel_commit_sweep]], [[feedback_precommit_stash_collision]])
covers concurrent *commits* in a shared checkout. This is a different failure mode: a sibling agent
writing plain files (no commit, no staging) that then show up in *my* `git status`/`git diff --stat`
and could be misreported as part of my change, or accidentally reverted if I run a broad
`git checkout -- <dir>` instead of scoping to the exact files I touched.

**How to apply:** when multiple agents may share one non-worktree checkout (the default here — no
`isolation: "worktree"`), scope the final diff/report to the exact file list from the task spec, not
to whatever `git status` shows. Use `git diff -- <file1> <file2> ...` (explicit paths) rather than a
bare `git diff` when composing the report. Never revert or `git checkout --` a path you didn't
intend to touch, even if it appears modified — verify with `git diff <path>` whose change it is
before deciding.
