---
name: cto-spawn-explicit-fable
description: "Spawning the cto agent without model: \"fable\" ran it on Opus despite model: fable in its frontmatter — always pass the model explicitly"
metadata:
  type: feedback
---

Always pass `model: "fable"` in the Agent call when spawning `cto`.

**Why:** 2026-09-29, transport-single-policy Ф4 audit — the cto agent's frontmatter says `model: fable`, but the
spawn without an explicit model ran on Opus; the owner noticed and asked for Fable. The rerun with an explicit
model worked and gave an independent second opinion (both returned BLOCK, Fable disagreed on two points).

**How to apply:** every `cto` spawn carries `model: "fable"`; if a phase verdict was already issued by the wrong
model, rerun on Fable with the first verdict passed as hypotheses to verify by running, not as facts.
