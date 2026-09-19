# Context7 — up-to-date library documentation

**Context7** is an MCP server that pulls up-to-date library documentation straight into Claude Code's context. When an agent works with any fast-moving library (frontend frameworks, ORMs, GUI toolkits, ML SDKs) — Context7 gives it fresh docs instead of the stale ones from its training data.

## Difference from qex and sentrux

| Server | Level | What it does |
|--------|---------|------------|
| **qex** | project-level (`.mcp.json`) | Semantic search over **your** code |
| **sentrux** | project-level (`.mcp.json`) | Architectural health of **your** project |
| **Context7** | **user-level** (`~/.claude.json`) | Up-to-date docs for **external** libraries |

Context7 is configured **once per machine**, not per project. That's why it's not in `.mcp.json`, but in `~/.claude.json`.

## Installation

> Quick install path — [`SETUP_GUIDE.md`](SETUP_GUIDE.md). Details below.

### Requirements

- **Node.js** ≥ 18 + npx

### Steps

```bash
# 1. Run setup (a browser opens for OAuth; free tier, no card needed)
npx -y ctx7 setup --claude

# 2. Restart Claude Code
```

Setup automatically adds the `context7` block to `~/.claude.json`.

### Verification

In Claude Code run `/mcp` — Context7 should appear in the server list.

Or check the file manually:

```bash
# macOS / Linux
cat ~/.claude.json | grep -A5 context7

# Windows (PowerShell)
Get-Content ~\.claude.json | Select-String -Pattern "context7" -Context 0,5
```

## Platform specifics

| Platform | Config path | Node install |
|-----------|-------------|----------------|
| macOS | `~/.claude.json` | `brew install node` |
| Linux | `~/.claude.json` | nvm or a package manager |
| Windows | `%USERPROFILE%\.claude.json` | [nodejs.org](https://nodejs.org) or `winget install OpenJS.NodeJS` |

## When it's useful

- A fast-moving framework (frontend, GUI, ORM, ML SDK)
- Version migrations (Pydantic v1 → v2, etc.)
- Any library where the LLM's knowledge is outdated

## When it's NOT needed

- Working only with the project's internal code → use qex
- Stable APIs (Python stdlib, SQLite) → Claude already knows them

## Troubleshooting

**Context7 doesn't respond:**
- Check `~/.claude.json` — there should be a block with `context7`
- Re-run `npx -y ctx7 setup --claude`
- Make sure Node.js ≥ 18: `node --version`

**`npx` not found:**
- Install Node.js (see the table above)
- After installing, restart your terminal

**Free tier — are there limits?**
- Yes, but it's enough for regular development. The rate limit is lenient.
## Launcher options

**Default**: context7 is configured at **user level**, not project level. Setup via `npx -y ctx7 setup --claude` (one-time, per machine). The `.mcp.json` in your project does **not** include context7 — that's intentional.

There is no per-project alternative — context7 is shared across all your Claude Code projects on a machine.

Re-run `npx -y ctx7 setup --claude` to refresh the user-level config.
