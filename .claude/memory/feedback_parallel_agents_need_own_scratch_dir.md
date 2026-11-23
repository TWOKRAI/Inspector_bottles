---
name: parallel-agents-need-own-scratch-dir
description: "Parallel agents sharing one scratchpad overwrite each other's helper scripts (inj_run.sh); give each agent its own subdirectory in the brief"
metadata:
  node_type: memory
  type: feedback
  last-verified: 2026-11-08
  originSessionId: 8bdcde24-884f-40a3-b367-8271ddbfa57a
  modified: 2026-11-08T17:35:16.297Z
---

When several agents run in parallel (injection matrices, reviews), the brief names a PRIVATE scratch subdirectory
(`<scratchpad>/own_<task>/`) for every helper script and log; the shared scratchpad root is for the lead only.

**Why:** 2026-11-08, atlas-passport: three agents wrote `inj_run.sh` into the same scratchpad. The 7.1b agent's first
runs executed the 7.1a agent's script and did `git checkout -- .` inside the 7.1a injection worktree, so the 7.1a
matrix results of that window became untrustworthy. The agent noticed only because the FAILED names were foreign.

**How to apply:** put `own_<task>/` into every agent brief that creates scripts; after any parallel batch ask each
agent for its control run (I0) and for the FAILED names it saw; treat a result whose test names do not belong to
the task as a sign of a collision.
Related: [[review-file-names-need-plan-prefix]]
