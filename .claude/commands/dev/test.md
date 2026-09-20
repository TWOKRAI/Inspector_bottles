---
description: Run the Tester agent (Sonnet) — write and run tests
---

Launch the **tester** agent (subagent_type: "tester", model: sonnet, `run_in_background: false` — the result is needed in this same turn).

Pass to it:
1. What to test: files, functions, modules
2. Acceptance criteria from the spec (if any)
3. Context: "Read CLAUDE.md, find existing tests for style"

After completion:
- Show the test results to the user
- If tests fail because of a bug in the code — report it, suggest sending it to Developer

## RED mode (`MODE: red`) — in the shared tree

If this is a RED tester ahead of `/dev:implement` (TDD-first): spawn tester in the shared tree
with `run_in_background: false` — there's no implementation yet per the step order; blindness
comes from the brief (forbidden paths), not from a worktree (Д45: a worktree costs +19…28k in <!-- lint-language: allow -->
nested `CLAUDE.md` overhead and is needed only for real fan-out —
`core/agents/_WORKTREE_PATTERN.md`). The brief follows the form
`.claude/plugins/dev/templates/executor-brief.md`. After RED, tester commits itself (explicit
paths) `test(...)` with `Refs:`.

What to test: $ARGUMENTS
