---
description: One-command project status snapshot — plans, architecture, tests, map, recent activity, memory.
---

Assemble a compact, single-screen snapshot of project state for the orchestrator
(and the user). Pure composition — gather from the sources below, each with a
**graceful fallback**: if a source is missing or a tool is unavailable, skip that
section (mark it `[--]`), never fail the whole report.

Constraints for the final report:
- **<= 40 lines**, ASCII only (no arrow / checkmark glyphs — Windows cp1251 safe).
- Tables or short lists, one section per line where possible.
- **Do not run the full test suite. Do not write any file.** This is read-only.

## Sections

### 1. Plans
Active plan + Task-checkbox progress. Resolve the plan with **date-tolerant**
globs — the seed convention is date-prefixed, identical to `/dev:implement` and
`/dev:ship` (do NOT use bare-slug paths; the `session-plan-status.sh` banner does,
but it is blind to date-prefixed plans):
- Derive the slug from the current branch (`git branch --show-current`, strip the
  `<type>/` prefix).
- single plan: newest match of `plans/*_<slug>.md`.
- multi-phase: newest match of `plans/*_<slug>/` -> read its `plan.md` **and**
  every `phase-*.md` (per-task checkboxes live in the phase files, not `plan.md`).
- Count `[DONE]` / `[IN_PROGRESS]` / `[PENDING]` task markers across those files
  -> `N/M done`.
- Fallback: no `plans/`, no matching plan, or a legacy plan with no date prefix
  -> `[--] no active plan`.

### 2. Architecture
Only if the sentrux MCP is connected **and** `.sentrux/rules.toml` exists:
- `mcp__sentrux__health` -> one-line score/grade + top bottleneck module.
- `mcp__sentrux__check_rules` -> count of rule violations.
- Fallback: sentrux not connected or no rules file -> `[--] sentrux not configured`.

### 3. Tests
Pick the cheap option — never run the full suite:
- If sentrux is connected: `mcp__sentrux__test_gaps` -> count of modules without tests.
- Else, a quick count only: `uv run pytest --collect-only -q | tail -1` -> collected test count.
- Fallback: neither available -> `[--] tests not measured`.

### 4. Map
- Module count: number of `CONTEXT.md` files under `src/` (proxy for documented modules).
- Staleness of `docs/PROJECT_CONTEXT.md`: compare its mtime with the last commit
  touching `src/` (`git log -1 --format=%cd --date=short -- src/`). If the map is
  older than the last `src/` change -> `[WARN] stale`.
- Fallback: no `docs/PROJECT_CONTEXT.md` -> `[--] no project map (run /core:quality:sync-context)`.

### 5. Recent
- Last entry under `docs/sessions/` (filename is the date) + its one-line summary.
- Last 3 commits: `git log -3 --format='%h %s'`.
- Fallback: no `docs/sessions/` -> show the commits only.

### 6. Memory
- First ~10 lines of `.claude/memory/MEMORY.md` (the index) — entry count + topics.
- Fallback: no memory index -> `[--] no project memory`.

## Output format

One ASCII block, **<= 40 lines**. Fill with real data; use `[--]` for skipped
sections and `[WARN]` for things that need attention. Example shape:

```
=== Project Dashboard: <repo name> ===

Plans     [OK]   feat/factory-orientation -> 2026-06-10_factory-orientation (8/14 done)
Arch      [OK]   sentrux grade B (0.78)   0 rule violations
Tests     [OK]   2001 collected           (sentrux: 3 modules w/o tests)
Map       [WARN] docs/PROJECT_CONTEXT.md stale (src changed since)
Recent    [OK]   2026-06-21 session  |  c777e31 feat(lint): ...
Memory    [OK]   18 entries indexed

Next: regenerate the project map -> /core:quality:sync-context
```

End with a single **Next:** line — the single most useful next action derived
from the sections above (address a `[WARN]`, or `/dev:plan-status` for plan detail).

$ARGUMENTS
