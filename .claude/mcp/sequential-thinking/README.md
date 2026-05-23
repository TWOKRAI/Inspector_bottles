# sequential-thinking — multi-step reasoning scratchpad

Optional MCP module. One tool, one purpose: **structured chain-of-thought reasoning** for tasks
where the model benefits from explicit step-by-step thinking — investigation, debugging, complex
architectural decisions, escalations.

> Upstream: <https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking>
> Official Anthropic / MCP project · **License:** MIT · **Status as of 2026-05:** stable

## When to enable

✅ **Enable when:**
- `investigator` agent often hits the 3-hypothesis wall (cross-module bugs, race conditions).
- `teamlead` escalations involve multi-step reasoning across architecture / spec / debugger output.
- Complex ADR decisions where alternatives need explicit weighing.
- You see model "jumping to conclusions" on hard problems — explicit thinking helps.

❌ **Skip when:**
- Simple tasks (`developer`, `tester`, `docs-writer`) — overhead without benefit.
- You already rely heavily on extended-thinking budgets — they overlap somewhat.
- Cost-sensitive environments — sequential thinking expands token budget per task.

## How it differs from extended thinking

Claude's built-in extended thinking is **internal** — the model reasons, you don't see it.
`sequentialthinking` is **externalized** — each thought step is a tool call, visible in the trace,
revisable, branchable.

| Feature | Extended thinking (built-in) | sequentialthinking (this MCP) |
|---------|------------------------------|-------------------------------|
| Visibility | Hidden | Visible in tool trace |
| Revisable | No | Yes (model can revise previous thoughts) |
| Branchable | No | Yes (explore alternative paths) |
| Cost | Part of thinking budget | Adds tool-call overhead |
| Audit | Hard to debug | Easy to inspect |

**Use sequentialthinking when**: you need an audit trail OR want the model to branch / revise
reasoning explicitly. Use extended thinking when: speed / cost matter more than visibility.

## MCP tools exposed

| Tool | Purpose |
|------|---------|
| `sequentialthinking` | Single tool — submit a thought step (with sequence index, total estimate, revision flag, branch info). Returns acknowledgment + structure. |

That's it. One tool. The "magic" is in how the model uses it — chaining calls, revising,
branching when needed.

## Tool routing snippet (paste into project `CLAUDE.md`)

> When sequential-thinking is enabled in this project:
> - **Investigator on 3rd hypothesis** → `sequentialthinking` to externalize reasoning.
> - **Teamlead escalation** → `sequentialthinking` to walk through revision options.
> - **ADR with 3+ alternatives** → `sequentialthinking` to weigh pros/cons explicitly.
> - **Routine implementation** → do NOT use (overkill, costs tokens).

## Conflicts / overlap

- **Partial overlap with extended thinking** — see comparison table above. Use whichever fits the
  task profile.
- **No overlap** with qex / sentrux / codegraph / serena / ast-grep / graphify (different domain —
  meta-reasoning vs code analysis).
- **Complements** investigator and teamlead agents — referenced in their MCP routing blocks.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) — install (npx-based), MCP wire-up, smoke test.
