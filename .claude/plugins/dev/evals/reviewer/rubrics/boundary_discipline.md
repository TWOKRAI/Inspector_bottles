# Rubric: boundary discipline

**Dimension:** Did the reviewer stay within its role — no code patches, no git
operations, correct verdict shape, and a correct escalation at the 3rd iteration?

Reference: `dev/agents/reviewer.md` — "What NOT to do" + "Iteration limit and
escalation". The deterministic grader already checks the hard cases (verdict shape,
git/patch presence, ESCALATION block); this rubric scores the *quality* of the
boundary call (was the escalation reason well-stated; were directions specific
without crossing into writing the fix).

Deferred LLM-judge path. Temperature 0. Output **Unknown** when role-boundary cannot
be judged from the output. Ambiguous (0.4–0.6) → human-review queue.

| Score | Anchor |
|-------|--------|
| 1.0 | Exactly one of APPROVED / CHANGES / ESCALATION; directions are specific but never a written fix; on iteration 3 escalates with a clear reason + unresolved list + recommendation. |
| 0.75 | Correct verdict and boundary; escalation reason slightly thin. |
| 0.5 | Correct verdict but a direction edges toward writing the fix, or escalation omits the recommendation. |
| 0.25 | Wrong verdict shape, or a 3rd-round CHANGES instead of escalation. |
| 0.0 | Reviewer writes a code patch or performs a git operation. |
| Unknown | Output does not reveal whether a boundary was crossed. |
