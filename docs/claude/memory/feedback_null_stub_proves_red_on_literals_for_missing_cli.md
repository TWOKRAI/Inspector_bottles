---
name: null-stub-proves-red-on-literals-for-missing-cli
description: "RED suite against a CLI that does not exist fails on \"can't open file\", not on literals; prove literals with a throwaway null stub and add anchors to negative tests / нулевая заглушка доказывает красный по литералам"
module: [scripts]
mechanism: [acceptance, test-assertions]
role: tester
metadata:
  type: feedback
---

When the script under test is not written yet, every subprocess test fails at the fixture-level exit-code assert ("can't open file"). That proves nothing about the literals.

**Why:** plans-progress Task 1.0+1.1 (2026-10-02): lead demanded "the literal check fails, not the exit code". A throwaway null stub (prints `[]`-like records with zero tasks, exit 0, writes `<html></html>`) turned 97 file-not-found reds into literal reds (`(0, 0) == (5, 20)`) and exposed 6 negative tests that a null implementation passes (empty-tasks, exit-0-without-baseline, tier-is-None).

**How to apply:** write the stub in the tree, run, read failures, fix every test that stays green with a pair (a positive anchor in the same test: a sibling plan with a real section, "without baseline exit 1" control, "info finding is printed"), then DELETE the stub and disclose it in the report. `ls` the dir afterwards.

Also: plans_ledger `status` prints `<plan>/plan.md: N/M, phase, ...` (read with a regex on the plan prefix); `close` needs `git init`+commit in tmp and refuses undated names; the repo has no `.venv` in a worktree — use the main tree's interpreter via `sys.executable`.
