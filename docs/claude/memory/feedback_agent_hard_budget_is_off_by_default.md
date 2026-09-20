---
name: agent-hard-budget-is-off-by-default
description: Subagent context ceiling — soft warning only (100k) unless the lead sets a hard cap per agent (.budget file) or via env; developer ran to 401k on 2026-09-20
metadata:
  type: feedback
---

The `agent-context-ceiling` PreToolUse hook (`.claude/plugins/core/hooks/_lib/agent_context_ceiling.py`)
warns at `start + 100k` (DEFAULT_SOFT) and then every +50k — a message the agent may ignore.
**The hard cap is OFF by default** (`hard is None`). It exists only when set: env
`AGENT_CONTEXT_HARD_BUDGET=<n>` (not in `.claude/settings.json` as of 2026-09-20), or a per-agent
file `$CLAUDE_PROJECT_DIR/.claude/logs/agents/<agent_id>.budget` with `soft=… hard=…`.

**Why:** measured 2026-09-20 on line-sim Task 1.1 — `developer` (Sonnet) ran to **401k tokens /
112 calls** with nothing stopping it; the owner asked "wasn't there a token limit in the seed" and
the honest answer was "there is, and the lead did not switch it on".

**How to apply:** for a hard cap, spawn with `run_in_background: true` (the id is known only after
spawn), immediately write `<id>.budget` (e.g. `soft=150000 hard=300000`), then wait for the
completion notification — "synchronous" in the project rules means "do not proceed without the
verdict", which a wait satisfies. A permanent cap is one line in `settings.json` `env` — the owner's
call, not the lead's. Related: [[feedback-claude-cli-backend-costs-a-full-session]].
