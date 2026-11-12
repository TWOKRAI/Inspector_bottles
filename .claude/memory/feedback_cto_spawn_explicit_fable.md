---
name: cto-spawn-explicit-fable
description: Review on reviewer+opus, merge gate on reviewer+sonnet, cto (Fable) only for heavy cases; always pass model explicitly
metadata:
  node_type: memory
  type: feedback
  originSessionId: 8bdcde24-884f-40a3-b367-8271ddbfa57a
  modified: 2026-11-08T17:55:57.238Z
---

Per-task review (express, rounds 1-2) is `reviewer` with `model: "opus"`. The merge gate is `reviewer` with
`model: "sonnet"`. `cto` (`model: "fable"`) is called only in heavy cases: a disputed or repeated BLOCK, or a complex
architecture decision. Never a routine merge gate, never per task.

**Why:** owner, 2026-11-08, in two steps. First: "ревью и приёмка на Опус, CTO в тяжёлых случаях" (the 0.1 and 1.1 gates
of atlas-passport had gone to `cto` on Fable because `.claude/CLAUDE.md` and the handoff say "CTO merge gate"). Later
the same day, after merge gates on Opus had been running: "для merge делаем соннет, а ревью опус". The merge gate
mostly re-runs checks the Opus review already made (trial merge, tests, index/validate counts), so Sonnet is enough.
Earlier, 2026-09-29: a `cto` spawn without an explicit model ran on Opus although its frontmatter says fable, so the
model is always passed explicitly.

**How to apply:** express review of a task = `reviewer` + `opus`; merge gate = `reviewer` + `sonnet`, reproduce by
running on a trial merge, verdict APPROVED/BLOCKED. Escalate to `cto` + `fable` only on a disputed verdict or a design
question; pass the first verdict as hypotheses to verify by running. Do not write "cto merge gate" into new plans and
handoffs; the atlas-passport plan/handoff still say it, read it as "reviewer sonnet gate". Do not stop agents already
running when the rule changes; the new rule applies to the next spawn.

Related: [[explicit-model-per-agent-role]]
