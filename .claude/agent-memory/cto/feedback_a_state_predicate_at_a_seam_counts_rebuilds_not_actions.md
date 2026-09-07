---
name: state-predicate-at-a-seam-counts-rebuilds-not-actions
description: When a voice/guard is placed at a shared seam (rebuild, apply, compose) and tests a STATE, its count means "applications", and every authorless caller of the seam (sweeper, retry loop) inflates it — verify "once per action" claims by listing origins, and always probe the retry road
metadata:
  type: feedback
---

Rule: a voice placed at a seam that many roads share, testing the resolved STATE rather than a transition, counts every pass through the seam. "Once per action" holds only if every caller of the seam is an action — list the callers by origin and find the one without a human (timer sweep, retry-on-failure), then run that road against the real log file before accepting the claim.

**Why:** Task 4.11 docstring said "the ONLY function called EXACTLY once per operator action" and listed two roads; grep found six call sites and one authorless origin (`ttl-sweeper`). Reproduced 2026-09-08: the sweep took a window slot with an unrelated key expiring, and on a stuck rebuild the retry road voiced on every tick. The prior stand had proven the Goal on `config.reload` only — the road nobody drove was the one that broke the claim.

**How to apply:** in any phase acceptance touching windowed voices or "suppressed: N" numbers, add two probes beyond the operator road: (1) the timer/sweep road with an UNRELATED key expiring, (2) the retry road with a broken receiver and a shortened window. Predict the line counts before running. Also: run a test file from a scratchpad copy only if it does not compute `REPO_ROOT` from `__file__` — `parents[4]` resolved into Temp and produced 4 false reds.
