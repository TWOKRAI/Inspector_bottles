---
name: new-cli-flag-red-is-all-argparse-exit2
description: RED for a new CLI flag is uniformly argparse exit 2; prove fixtures with a throwaway reference impl and anchor every exit-2 validation test with a valid-value run
metadata:
  type: feedback
---

When the task adds flags (`--now`, `--who`), every test that passes the flag is red today because argparse
exits 2 ("unrecognized arguments") — red for the wrong reason, and fixture bugs hide behind it.

**Why:** Task 5.2 of plans-progress-dashboard: 77/77 red looked fine, but a throwaway reference implementation
(scratchpad, from DESIGN only) exposed 3 fixture bugs of mine (empty initial commit, control worktree never
created, header branch without a slash `main` cannot match `тип/имя`). Exit-2 validation tests (`6x`, tz in --now,
`--who --json`) would pass TODAY by argparse alone, so each must first run the same call with a valid value
and demand exit 0.

**How to apply:** (1) write a ~100-line reference impl in the scratchpad, copy the test file with PROGRESS patched
via `re.sub(..., lambda m: ...)` (a plain replacement string eats backslashes), run to green, delete the copy;
(2) run a null stub (roots=[]) to list which tests pass without any behaviour and say so; (3) a real `git init`
fixture with zero files makes `git commit` fail — always add a file. See [[null-stub-proves-red-on-literals-for-a-missing-cli]].
