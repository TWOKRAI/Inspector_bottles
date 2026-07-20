---
name: feedback-parallel-commit-sweep
description: Staged-but-uncommitted files get swept into a concurrently running sibling agent's commit when both work in the same tree without worktree isolation
metadata:
  type: feedback
---

While working on `fix/backend-ctl-hardening` (Task 1.3), I `git add`'d exactly my two
files (`backend_ctl/mcp_server_sdk.py`, a new test file) and ran `git commit`. The
pre-commit hook fired, but by the time it finished a **sibling agent working on Task
2.1 in the same working tree** had already run its own `git commit` (likely via a
broader `git add`/`-a`) and swept up my staged files into *their* commit
(`3a0bf262`, message about Task 2.1 only). My own `git commit` immediately after found
nothing left staged.

Verified with `git show <their-hash> -- <my-file>`: my diff landed byte-for-byte
correct — no content was lost or corrupted, only the commit boundary/message is wrong
(Task 1.3's fix has no dedicated commit/trailers of its own).

**Why:** two agents editing the same non-worktree checkout race on the shared index;
whoever calls `git commit` second finds the other's staged files already consumed.
This is a fresh concrete instance of the project's documented
`docs/claude/memory/feedback_parallel_agents_commit_race.md` pattern — confirms it
also bites on exactly 2 agents, not just 5+.

**How to apply:** after `git commit` returns, always `git log --oneline -3` +
`git show <hash> --stat` to confirm the commit you just made actually contains only
your files with your message — do not trust the commit command's exit code alone.
If your files vanished from `git status` without your commit succeeding, they were
swept by a sibling; check the most recent commit(s) by other authors/messages for
your diff before assuming data loss. Do NOT `git reset --soft`/rebase to un-bundle
it while sibling agents are still actively committing in the same tree (observed
`mcp_tools.py`/`recorder.py` changing mid-investigation here) — report the collision
to the orchestrator instead of doing unilateral history surgery on a shared branch.
