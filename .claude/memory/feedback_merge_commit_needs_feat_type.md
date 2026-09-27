---
name: feedback-merge-commit-needs-feat-type
description: "The commit-msg hook rejects type 'merge'; merge worktree branches with a feat/fix subject, and git merge -F - does not read stdin."
metadata:
  type: feedback
  last-verified: 2026-09-27
---

Merging a task worktree branch into the plan branch: `git merge --no-ff -F <file>` with a Conventional type the
hook allows (`feat(scope): …`, trailers Why/Layer/Refs). A `merge(...)` subject is rejected by
`.git/hooks/commit-msg` AFTER the merge is staged — finish it with `git commit -F <file>` (fixed subject), do not
re-run the merge. `git merge -F -` fails with "could not read file '-'" (no stdin), nothing is merged.

**Why:** 2026-09-27, merge of `wt/t2j-dev` took three attempts; the half-done merge left 17 files staged.
**How to apply:** write the message to a scratchpad file first; check `git status` after a rejected merge commit.
Related: [[feedback-injection-scripts-on-committed-code]].
