---
description: System test-drive — one command to check MCP, agents, skills, hooks, indexes. After `claude-kit new` and periodically.
---

Run a health check of the whole Claude-Kit system. This is a **read-only diagnostic** — it fixes nothing, it only reports what works, what doesn't, and what needs attention.

## What it checks

1. **MCP layer** — which MCP servers are available:
   - qex (binary + Ollama for embeddings)
   - sentrux (binary)
   - context7 (cfg in `~/.claude.json` or `.mcp.json`)
   - optional MCP from `.mcp.json`: codegraph, ast-grep, serena, graphify, github, qt-mcp, playwright, sequential-thinking

2. **Config layer** — configuration validity:
   - `settings.json` — JSON is valid + critical deny/ask/allow are in place (via `/core:quality:lint-settings`)
   - `agents/*/*.md` — frontmatter is valid (via `/core:quality:lint-agents`)

3. **Routing consistency** — agent routing blocks match `.claude/plugins/core/mcp/ROUTING.md`:
   - Every `mcp:server:tool` mentioned in agents is in ROUTING.md
   - No orphan tools in ROUTING.md (mentioned but unused by anyone)

3b. **Content lints** — unified language + command namespacing:
   - **Language** (`lint_language.py`) — no Cyrillic in `agents/` and `modes/` (EN-only zones; FAIL on regression). Bodies of `commands/`/`skills/`, awaiting a deferred EN pass, are non-blocking WARN.
   - **Namespacing** (`lint_namespacing.py`) — no legacy flat command names (`/plan` → `/dev:plan` etc.) in plugin content. <!-- lint-namespacing: ignore -->

4. **Indexes** — state of MCP indexes (if active):
   - qex: `qex --version` + (opt.) index exists
   - sentrux: `sentrux --version` + (opt.) recent scan

5. **Hooks** — executability:
   - Every `.sh` in `.claude/plugins/*/hooks/` has the executable bit
   - Test run of each hook with empty stdin (smoke check, must not crash)
   - **Git hooks** (`.git/hooks/`, opt-in, per-machine): whether `post-commit`
     (qex auto-reindex, `/mcp-qex:install-reindex-hook`) and `pre-push` (sentrux gate,
     `/mcp-sentrux:install-pre-push`) are installed. Missing is normal (not a warn, visible in verbose).

6. **Plans** — plan integrity:
   - `plans/` exists
   - No orphan folders (multi-phase without a `plan.md` inside)
   - Refs traceability of recent commits: commits on the current branch with Refs point to existing files

7. **Harness-bloat** — ROADMAP § J ceilings (advisory soft-warning, keeps the system in the "smart zone"):
   - **agents ≤ 12** in one team plugin (seed: `dev` is exactly 12 — at the ceiling)
   - **hooks ≤ 15** in one plugin (seed: `core` is exactly 15 — at the ceiling)
   - **skills ≤ 15** total across all plugins (seed: ~9)
   - **MCP ≤ 8** configured servers in `.mcp.json` (default: ~4)
   - Counted **per-plugin** for agents/hooks (the bloat unit is the plugin; a flat total
     would add dev+core and false-trigger on the seed itself), **total** for skills/MCP.
   - **Only WARN, never FAIL** — crossing the ceiling is a signal to consolidate
     (collapse/merge), not a broken system. A fresh `claude-kit new` = clean
     (everything at or below the ceiling); WARN appears when the project **outgrows** § J.

## How to run it

```bash
# Run from the project root (where .claude/ lives)
bash .claude/plugins/core/scripts/doctor.sh

# Or with verbose output
bash .claude/plugins/core/scripts/doctor.sh --verbose
```

## Output

The command prints a summary table with `[OK]` / `[WARN]` / `[FAIL]` labels + a short description. Final verdict at the end.

Example:
```
=== Claude-Kit System Health ===

MCP servers       [OK]    qex UP  ollama UP  sentrux UP  context7 cfg
Settings lint     [OK]
Agents lint       [OK]    19/19 valid
Routing sync      [OK]    all mcp:server:tool references valid
Language lint     [OK]    agents/ + modes/ are EN-clean (N non-blocking warn(s) in deferred bodies)
Namespacing lint  [OK]    no flat command names
Indexes           [WARN]  qex index age: 5 days (consider /mcp-qex:qex-reindex)
Hooks executable  [OK]    14/14 +x
Git hooks         [OK]    post-commit installed (qex auto-reindex)
Plans integrity   [OK]    3 plans, no orphans
Harness-bloat     [OK]    agents:12/12(dev) hooks:15/15(core) skills:9/15 mcp:4/8 — within §J ceilings

Verdict: ✅ Healthy (1 warning — informational)
```

## When to use it

- **After `claude-kit new`** — confirm the infrastructure deployed correctly.
- **Periodically** — once a week / when returning to the project after a break (drift check).
- **Before a long work session** — a quick check that MCP is UP, so agents don't burn tokens on silent failures.
- **When suspecting a problem** — "why are agents behaving strangely?" → `/core:quality:doctor` will show if MCP isn't responding.

## Exit codes (for CI)

- `0` — everything OK (there can be WARNs, but no critical problems)
- `1` — there is a FAIL (something critical isn't working)
- `2` — there is FAIL + WARN

## Auto-fix (out of scope for v1)

This command **only diagnoses**. For fixes, see the suggestions in the output:
- `WARN qex index age` → `/mcp-qex:qex-reindex`
- `FAIL Ollama DOWN` → `ollama serve` or `/core:infra:cold-start`
- `FAIL Settings lint` → fix `.claude/settings.json` by hand
- `FAIL Routing sync` → edit agent routing blocks to mention only tools from ROUTING.md
- `FAIL Language lint` → translate the Cyrillic in `agents/`/`modes/` to EN (or mark it `<!-- lint-language: allow -->`)
- `FAIL Namespacing lint` → replace flat command names with namespaced ones (see `docs/plugin-namespacing.md`)
- `WARN Harness-bloat` → the project crossed the § J ceiling: collapse/merge the extra agents/hooks/skills or disable unused MCP in `enabled.yaml` (advisory — non-blocking)

$ARGUMENTS
