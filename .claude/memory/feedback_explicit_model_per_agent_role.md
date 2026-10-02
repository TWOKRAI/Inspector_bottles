---
name: explicit-model-per-agent-role
description: Owner rule — always pass `model` explicitly when launching agents; reviewer and teamlead on opus, developer and tester on sonnet, super-reviewer (cto) on fable
metadata:
  type: feedback
---

When launching an agent with the Agent tool, pass `model` explicitly. Mapping (owner, 2026-10-02): `reviewer` = opus, `teamlead` = opus, `developer` / `tester` / `debugger` = sonnet, super-reviewer (`cto`) = fable.

**Why:** the reviewer was launched without `model` during the prompt-audit review. Its frontmatter says `opus`, but the journal (`data/team-journal.jsonl`) does not record the model, so Opus could not be confirmed. The owner wanted the review on Opus.

**How to apply:** pass `model: "opus"` / `"sonnet"` / `"fable"` on every Agent call, and state the model in the brief. Do not rely on the frontmatter default alone. The cto (Fable) is the "super-reviewer": once per phase or disputed decision, never per task.

Related: [[always-latest-models]]
