---
name: agent-models-sonnet-impl-opus-review
description: Owner's standing choice of subagent models — implementation on Sonnet 5.5, review on Opus 5.5; the lead does not write the code itself
metadata:
  type: feedback
---

Implementation subagents (`developer`, `tester`, `debugger`) run on **Sonnet 5.5** (`model: "sonnet"`);
review (`reviewer`) runs on **Opus 5.5** (`model: "opus"`). Stated by the owner on 2026-09-30 twice
(handoff `2026-09-30_line-sim-r5-r6-stroke-next-proto-run.md`, then the next session's opening message).

**Why:** the owner wants code written by the cheaper model and judged by the stronger one; the lead's context
is kept for spec, measurements and break-injection.

**How to apply:** pass `model` explicitly on every Agent call, do not rely on agent frontmatter. `teamlead`
(Opus) stays the escalation step after two failed review iterations — say so when switching.
Stand and branch etiquette with neighbour sessions: [[shared-stand-and-tests-protocol]].
