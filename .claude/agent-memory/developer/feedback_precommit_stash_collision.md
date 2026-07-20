---
name: feedback-precommit-stash-collision
description: pre-commit's own stash-unstaged-files isolation mechanism (not git stash) can fail to restore when a sibling agent commits concurrently in the same non-worktree checkout, orphaning a patch file and blocking the commit entirely
metadata:
  type: feedback
---

While closing Task 2.2 of `plans/backend-ctl-hardening.md` (branch `fix/backend-ctl-hardening`),
`git commit -F <msgfile> -- backend_ctl/audit.py backend_ctl/mcp_tools.py backend_ctl/tests/test_audit_threading.py`
failed three times in a row with the same error, even though my three files were staged
correctly and untouched by anyone else:

```
[WARNING] Unstaged files detected.
[INFO] Stashing unstaged files to C:\Users\...\.cache\pre-commit\patch<N>.
...hooks run and pass...
[WARNING] Stashed changes conflicted with hook auto-fixes... Rolling back fixes...
error: patch failed: docs/sessions/2026-07-20.md:243
error: docs/sessions/2026-07-20.md: patch does not apply
```

**Root cause:** pre-commit's `staged_files_only` isolation (separate from `git stash`) snapshots
*all* unstaged changes tree-wide into a patch file, runs hooks against the staged tree only, then
tries to `git apply` that patch back. One of the hooks (`append session log to docs/sessions/`)
also writes to `docs/sessions/2026-07-20.md` on every commit by every agent. Because a sibling
agent was committing concurrently in the same working tree (no worktree isolation — see
[[feedback-parallel-commit-sweep]] and the project's `feedback_parallel_agents_commit_race`), the
file had already moved by the time my snapshot tried to re-apply, so the patch no longer matched
and `git apply` aborted. pre-commit does not retry — it just fails the whole commit and leaves the
patch orphaned in `~/.cache/pre-commit/patch<N>`.

**This is a different failure mode from the sibling-sweep** documented in
[[feedback-parallel-commit-sweep]] (where a sibling's `git commit` silently absorbed my staged
files into their commit, no data loss, wrong commit boundary). Here nothing gets committed at all
— the commit aborts outright — but a sibling's genuinely uncommitted work (their unstaged edits to
files *outside* my pathspec, e.g. `mcp_server_sdk.py`/`test_mcp_server_sdk.py` in this incident)
can be **lost from the working tree** if pre-commit's rollback itself only partially restores
before erroring. Always check for an orphaned patch file named in the `[INFO] Stashing...` line
before assuming their edits are gone — it usually still holds the diff and can be recovered with
`git apply <that patch path>` (may need `--reject` if the base has moved further).

**Why:** the project's `append session log` pre-commit hook writes to one shared file
(`docs/sessions/<date>.md`) on every single commit; under 2+ agents committing in the same
non-worktree checkout, that shared-file contention makes the failure near-certain, not just
theoretical — it reproduced identically 3/3 tries here.

**How to apply:**
- Before retrying a failed commit of this shape, run `git status --short` tree-wide and specifically
  check whether files *outside* your own pathspec (that used to show as modified) have silently
  reverted to HEAD content — that is the signature of this incident, not a clean state.
- Do not blindly retry more than 2-3 times hoping the sibling finishes — each failure invokes the
  hooks again (cost) and leaves another orphaned patch. If it fails identically 2+ times on the
  same file/line, stop and escalate to the orchestrator instead of continuing to retry; this is a
  cross-agent infra collision, not something fixable within a single agent's task scope.
- Never try to hand-fix the colliding shared file (e.g. `docs/sessions/*.md`) yourself unless that
  file is explicitly in your task's `Files:` list — you'll likely collide again with the same
  sibling.
- Verify your OWN target files' content survived every failed attempt (`grep` for a known marker)
  before the eventual successful commit — pre-commit's stash/rollback dance touches the whole tree,
  not just the colliding file, so treat "commit failed" as "re-verify everything," not "nothing
  changed."
