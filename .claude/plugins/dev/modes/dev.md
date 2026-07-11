# Dev Mode — Development Team

Loaded for tasks: write code, implement a feature, fix a bug, refactor, migrate, write tests, review, write code documentation.

> **Before starting**, read `.claude/modes/_stack.md` — it contains the stack, layers, and conventions for this specific project.

## Pipeline (Contract-first TDD)

```
spec-writer → manager → developer(INTERFACE, only if new-*/public-api-change) → tester(RED, failing-test against interface) → developer/teamlead(GREEN, min impl) → [refactor] → tester(regression) → (debugger on FAIL) → reviewer → /dev:ship
```

**The order is strict and grounded in two practices:**

1. **Contract-first** — for a new module or public API change, a formal contract in code (`interface.py` with Protocol + DbC `Pre:`/`Post:`) is written first, then a test against the contract, then the implementation. Without this, the test relies on a prose spec restatement — implementation and test diverge.
2. **RED-first** — a failing test comes **before** the implementation. Without this, the implementer agent fits tests to broken code (Pocock: "algorithmic optimization — the model writes buggy code, then writes a test confirming that incorrect behavior"). RED is a structural anti-cheat.

Branch on the `Module contract:` field in the Task (see `manager.md`):
- `new-full` / `new-lite` / `public-api-change` → INTERFACE stage is present
- `impl-only` / `n/a` → INTERFACE skipped, contract already exists in the repo or there was none (bug fix without a formal contract is acceptable — tester notes this in the report)

Details on tester modes — see [`agents/tester.md`](../agents/tester.md) → "Two modes". Details on the INTERFACE stage — `module-contract` skill.

The `/dev:pipeline` skill runs the full chain with failure-recovery via the debugger.

## Team composition (`.claude/plugins/dev/agents/`)

| Agent | Model | Skill | When to call |
|-------|-------|-------|--------------|
| **spec-writer** | Sonnet 4.6 | `/dev:spec:spec`, `/dev:spec:spec-sync` | Living product spec — from the user's perspective |
| **manager** | Sonnet 4.6 | `/dev:plan` | Decompose a phase into Task X.Y with complexity levels. Does NOT write code |
| **developer** | Sonnet 4.6 | `/dev:implement` | Standard Task implementation per spec (Middle/Middle+). Code + smoke-test + commit |
| **teamlead** | Opus 4.8 | Agent tool | Senior+: architecture, refactoring, integration. Escalation on 3rd review/debug iteration |
| **tester** | Sonnet 4.6 | `/dev:test` | Pytest against acceptance criteria from spec. Does NOT change logic |
| **debugger** | Sonnet 4.6 | `/dev:debug` | Reproduce → hypotheses → root cause. Fixes within scope or delivers a diagnosis |
| **investigator** | Opus 4.8 | Agent tool | Read-only diagnosis of cross-module problems. Does not write code, delivers a report |
| **reviewer** | Opus 4.8 | `/dev:review` | Full review (10+ files, architecture, security). Max 2 iterations — then escalate to teamlead. Does NOT write code |
| **docs-writer** | Haiku 4.5 | `/core:team:docs` | Simple docs: docstrings, module README, STATUS.md |
| **tech-writer** | Sonnet 4.6 | Agent tool | Complex docs: DECISIONS.md (ADR), ARCHITECTURE.md, MIGRATION_*.md, RFC-*.md |

## Boundary rules

- **developer vs teamlead** — teamlead for architecture/refactoring (Opus); developer for standard implementation (Sonnet). When in doubt — developer
- **debugger vs investigator** — debugger fixes within scope (1-5 lines); investigator read-only diagnoses cross-module / architectural problems
- **reviewer vs teamlead** — reviewer only reads and points out issues; teamlead writes code (express review for ≤3 files or Senior+ implementation)
- **docs-writer vs tech-writer** — ADR / ARCHITECTURE / MIGRATION / RFC → tech-writer; everything else → docs-writer
- **3 iterations — stop** — reviewer does not approve → teamlead escalation; debugger has not found root cause in 3 hypotheses → investigator or teamlead escalation
- **Parallel delegation** — for independent subtasks, call agents in a single message (multiple Agent tool calls), not sequentially. For a whole plan with independent Tasks, `/dev:pipeline` has an opt-in **Parallel mode** (worktree-isolated developer/tester per Task) — see [`commands/pipeline.md`](../commands/pipeline.md)

## Module Design Discipline (contract-first)

When creating a new **public** module — follow contract-first: a module is born as a "contract + example tests" pair; the implementation is written after.

| Level | When | Artifacts |
|-------|------|-----------|
| **full** | package module (≥3 files or ≥2 public classes) | `README.md` + `__init__.py` (`__all__`) + `interface.py` (Protocol + DbC) + `_impl/` + `tests/contract/test_<module>.py` |
| **lite** | single-file module with a public API | `<module>.py` with module docstring (Purpose/API/Stability) + `__all__` + DbC in public functions + `tests/contract/test_<module>.py` |
| **none** | module is private (`_*`) or < 50 lines or has no `__all__` | discipline does not apply |

**Design by Contract** — pre/post/invariants in docstrings (convention, no `icontract`/`deal`). Each Pre/Post line is covered by at least one given/when/then test in `tests/contract/`.

**The `module-contract` skill** auto-invokes when a module creation is intended and provides inline structure examples + checklists.

**Reviewer** checks compliance on PR via the **Module Contract Compliance** specialization (see `reviewer.md`). Activation/skip rules and MCP routing are described there.

**Stability marker** — each module declares its level in the README or module docstring:
`**Stability:** contract` (full) / `lite` / `partial` / `legacy`. Legacy → brought up to `contract` or `lite` at the first significant touch.

## Common scenarios

```
Mid-complexity task                 →  /dev:pipeline
New feature — step by step          →  /dev:plan  →  /dev:implement  →  /dev:test  →  /dev:review  →  /dev:ship
Architectural decision / refactor   →  teamlead via Agent tool (no skill wrapper)
Failing test / regression           →  /dev:debug
Cross-module architectural bug      →  investigator via Agent tool
ADR (architectural decision)        →  /dev:adr <title>  (wrapper over tech-writer)
Migration guide / ARCHITECTURE      →  tech-writer via Agent tool
Living spec                         →  /dev:spec:spec  → user edits → /dev:spec:spec-sync
Quick diff check                    →  /dev:ship  (tests + linter + diff review)
System health check                 →  /core:quality:doctor (MCP + agents + hooks + indexes + plans)
Architecture diagrams stale         →  /core:infra:diagrams (pyreverse + pydeps + mermaid)
Team roster                         →  /core:team:team
```

## MCP control-rail (flow-stage → primary MCP → fallback)

Each pipeline stage leans on a primary MCP, with a no-MCP fallback so the flow
never stalls when a server is down. This is a **flow summary only** — canonical
per-server tool lists, conditional guards, and health-fallbacks live in
[`core/mcp/ROUTING.md`](../../core/mcp/ROUTING.md); do not re-document tool
semantics here (that would create a second source to keep in sync).

| Flow stage | Primary MCP | Fallback (no MCP) |
|-----------|-------------|-------------------|
| **plan** (manager) | `mcp:qex:search_code` (recon) + `mcp:sentrux:health` / `mcp:sentrux:dsm` (architecture) | `Grep` + read module READMEs |
| **INTERFACE** | `mcp:codegraph:codegraph_explore` — blast radius of the new/changed API | `git diff` + `Grep` for call sites |
| **RED** (tester) | `mcp:qex:search_code` — edge cases in related code | `Grep` by symbol + read neighbors |
| **GREEN** (developer/teamlead) | `mcp:serena:rename_symbol` / `find_referencing_symbols` (symbol ops) + `mcp:context7:query-docs` (library API) + `mcp:ast-grep:scan` (codemod) | `WebFetch` for docs + `Grep` / `Edit` |
| **regression** (tester) | `mcp:sentrux:test_gaps` — uncovered zones | `pytest --cov` read by hand |
| **review** (reviewer) | `mcp:sentrux:check_rules` (invariants) + `mcp:codegraph:codegraph_explore` | manual checklist + `git diff` |
| **verify** (done) | `verify-done` skill (see Skills routing below) — adds `mcp:qt-mcp:qt_snapshot` / `mcp:playwright:browser_navigate` for GUI/web | `pytest` / `pytest-qt` / `curl` + HTML check |
| **graph** (architecture map) | `/graphify` skill (primary) — reads `graphify-out/graph.json`; optional live layer `mcp:graphify:query_graph` | read `GRAPH_REPORT.md` / `graph.json` by hand |

When an MCP is not in the project's `.mcp.json`, fall back to the right-hand column
rather than handing the stage to a subagent that would just `Grep` blindly.

## Skills routing — when the orchestrator calls a skill

Skills augment commands and agents with behavioral patterns. When it is appropriate to call:

- **Before `/dev:plan`, if the idea is fuzzy** → `brainstorm` (2-4 distinct approaches with trade-offs).
- **Before `/dev:implement` in an unfamiliar area of the codebase** → `zoom-out` (module map via graphify/sentrux/codegraph).
- **The plan feels fragile** → `grill-me` (relentless interview across decision branches).
- **State/UI sanity check before committing** → `prototype` (LOGIC for state-machine, UI for web variations).
- **Before `/dev:ship` / final "done"** → `verify-done` (architectural sanity: sentrux + codegraph + playwright if web).
- **When "be brief", "fewer tokens"** → `caveman` (compression filter for the whole session).

## Coordination rules

The coordinator (Opus) does NOT write code itself when a task is delegated. Roles:
- Opus — reads the user's spec, plans the strategy, delegates, checks agent output
- Sonnet agents — heavy lifting in their own context windows (developer, tester, manager, debugger)
- Opus agents — critical decisions (reviewer, teamlead, investigator)

Exception: if the task is trivial (<30 lines, one file) — the coordinator may do it directly without delegating.

## Memory discipline (capture at Task boundary)

At every **Task boundary** (Task X.Y done, before moving to X.Y+1) and after any
**verified transition** (red→green, fix confirmed, non-trivial decision made) — run
the capture-rail check from `.claude/CLAUDE.md` → "Memory (OVERRIDE)" (the
capture-rail "when to capture" rules). If the WHEN-gate fires (fix took >1 attempt,
recurring trap, the user
gave a rule/preference, or a non-obvious decision not already stored in
code/git/plan) → write a `feedback`/`project` entry via `/core:memory:remember`.
If nothing qualifies → skip (do not invent lessons — see the FORBID list). This
keeps long-term context flowing into `.claude/memory/` **during** work, not only at
`/core:team:wrap-up`.

## Plans hierarchy

Where plans are stored — see `.claude/modes/_stack.md` (section "Plans"). Typical templates:

- **Single root:** `plans/<slug>.md` (simple project)
- **By scope:** `apps/{app}/plans/` (per-app in monorepo), `projects/{slug}/plans/` (per-project in multi-zone repo)

Manager at `/dev:plan` picks the correct location based on task context and `_stack.md`.
