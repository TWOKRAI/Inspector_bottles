---
name: context-budget
description: >
  Audit what consumes the context window in THIS project's .claude/ setup and
  report a prioritized prune list. Read-only diagnostic — makes no changes.
  Use when the user asks "what's eating my context", "audit token budget",
  "why is the baseline so big", "context cost", "which plugins/MCP to disable",
  "reduce token usage", or invokes "/context-budget". Distinct from `caveman`
  (compresses live output) — this audits the always-loaded baseline.
---

# Context budget audit

Every session pays a **fixed baseline** before the user types anything: system
prompt + tool/MCP schemas + `CLAUDE.md` + always-loaded rules + agent/skill
descriptions. This skill measures that baseline, finds the heavy items, and
hands the user a ranked prune list. **Diagnostic only — propose, never edit.**

## Workflow

### 1. Get the live breakdown first

Ask the user to run the built-in `/context` command (it shows the real
context-window split: system prompt, tools, MCP, memory, messages). If they
paste it, anchor every estimate below to those real numbers. If not, estimate
from disk (step 2) and say the numbers are approximate (`chars ÷ 4 ≈ tokens`).

### 2. Enumerate the always-loaded components

Read the project's actual config — do not guess:

- **MCP servers (usually the biggest cost).** Which plugins are `enabled: true`
  in `enabled.yaml`? Each ON MCP server loads its full tool schemas every turn
  (a 20-tool server ≈ ~14k tokens; several servers ≈ tens of thousands). This is
  the **#1 prune target.** Check whether tool-search deferral is on
  (`ENABLE_TOOL_SEARCH` in `settings.json` `env`) — if yes, the per-turn schema
  cost collapses to near-zero and MCP servers are cheap to keep.
- **CLAUDE.md chain.** `wc -c` on the root `CLAUDE.md` + `.claude/CLAUDE.md` +
  any always-loaded `.claude/rules/*` and `.claude/modes/_stack.md`. Target: the
  always-on prose under ~200 lines / a few hundred tokens. Flag anything bloated.
- **Agents.** Count agent definitions (composed under `.claude/plugins/*/agents/`,
  or flat in a non-plugin project); flag oversized `description` fields — the
  descriptions, not the bodies, load into the picker.
- **Skills.** Count `SKILL.md` files (under `.claude/plugins/*/skills/*/`); each
  skill's frontmatter `description` is always loaded for matching. Flag
  redundant/overlapping skills.

Rough sizing command (adapt to the project):

```bash
echo "== CLAUDE.md chain =="; wc -c CLAUDE.md .claude/CLAUDE.md .claude/modes/_stack.md 2>/dev/null
echo "== agents =="; wc -l .claude/plugins/*/agents/*.md 2>/dev/null | tail -1
echo "== skills =="; ls .claude/plugins/*/skills/*/SKILL.md 2>/dev/null | wc -l
echo "== enabled MCP =="; grep -nE "enabled: true|source:" .claude/enabled.yaml 2>/dev/null
```

### 3. Report — ranked prune list

Output a table sorted by estimated cost, with a concrete, reversible action and
a **quality-risk** column (the user cares about code quality, not just tokens):

| Component | Est. tokens / turn | Action | Quality risk |
|-----------|--------------------|--------|--------------|
| mcp-X (ON, unused this project) | ~14k | disable in `enabled.yaml` OR turn on tool-search | none |
| CLAUDE.md (480 lines) | ~6k | move workflow-specific blocks to skills | none |
| skills A/B (overlapping) | ~0.3k | merge or drop one | low |

### 4. Recommend in priority order, lowest-risk first

1. **Turn on MCP tool-search deferral** (`ENABLE_TOOL_SEARCH`) — biggest win,
   zero quality risk, keeps every server available.
2. **Disable MCP servers this project never uses** (`enabled.yaml`) — only if
   genuinely unused; check the agent routing first.
3. **Trim the CLAUDE.md chain** — relocate rarely-needed instructions to
   on-demand skills; keep the always-on file lean.
4. **Drop/merge redundant skills & oversized agent descriptions.**

End with the **estimated total baseline saving** and a one-line reminder that
nothing was changed — the user applies the cuts they agree with.

## Guardrails

- **Read-only.** Never edit `enabled.yaml`, `CLAUDE.md`, or settings here —
  output recommendations and let the user act.
- **Don't recommend disabling load-bearing MCP** (the ones the project's agents
  route to). Prefer tool-search deferral over disabling a useful server.
- **Estimates are estimates.** Label them as such unless anchored to real
  `/context` output. Never present `chars ÷ 4` as exact.
