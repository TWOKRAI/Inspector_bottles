---
description: Rebuild docs/PROJECT_CONTEXT.md from per-module CONTEXT.md and DECISIONS.md
---

# /core:quality:sync-context — update the project-wide context registry

Runs `scripts/aggregate_context` to build the aggregate registry
of per-module knowledge in `docs/PROJECT_CONTEXT.md`.

## When to use it

- After creating a new `<module>/CONTEXT.md` or `<module>/DECISIONS.md`
- After adding a new ADR to an existing module's `DECISIONS.md`
- After renaming a module or changing `module_code` in the frontmatter
- In CI — to guarantee the registry doesn't drift

## Usage

```
/core:quality:sync-context              # write mode — update the registry
/core:quality:sync-context --check      # CI mode — diff + exit 1 on drift
/core:quality:sync-context --list       # list the registered sync modules
/core:quality:sync-context --only render_context   # a single module only
```

## What it does

1. Scans the project, finds every `**/CONTEXT.md` and `**/DECISIONS.md`
   (with exclusions: `_archive`, `node_modules`, `.venv`, `__pycache__`, …)
2. Parses the per-module files, extracts Purpose / sections / ADR headers.
3. Renders three tables into `docs/PROJECT_CONTEXT.md` between the markers
   `CONTEXT-INDEX`, `ADR-CODES`, `ADR-INDEX`.
4. Does **not touch** text outside the markers.

## Pre-requisites

- `docs/PROJECT_CONTEXT.md` **is seeded by bootstrap** (`claude-kit-project new`)
  together with the starter `src/<package>/CONTEXT.md`. If the file is missing (legacy project) —
  create it from `.claude/plugins/core/templates/PROJECT_CONTEXT.template.md`.
- At least one module has a CONTEXT.md or DECISIONS.md (a fresh project already has
  `src/<package>/CONTEXT.md`).

If the registry file is missing — the script prints a human-readable error and
exits 2.

## Sections of a per-module CONTEXT.md

Template: `.claude/plugins/core/templates/CONTEXT.template.md` (all sections are optional,
keep only what's non-trivial):

- **Purpose** — what the module does and why (1-3 sentences).
- **Key decisions** — links to ADRs / anchor design decisions.
- **Gotchas** — footguns and non-obvious traps (the most valuable part for an agent).
- **Glossary** — local terms that mean something different here than in the industry.
- **Open questions** — deliberately unresolved (don't touch without agreement).
- **Migration notes** — important migrations and why legacy code still lives on.

The aggregator indexes whether these sections are present (columns P/K/G/Gl/O/M in the registry),
it does not touch the CONTEXT.md text itself.

## Why this is in the seed

The pattern is ported from Inspector_bottles (20+ modules with
DECISIONS.md there). Benefit for the agentic system: on entering module X
an agent immediately reads `<X>/CONTEXT.md` — it knows the Gotchas, design decisions,
and glossary. Reduces "blind reading" of the source.

## Related commands

- `/dev:adr` — create a **global** (cross-module) ADR in `docs/claude/DECISIONS/`
- `/mcp-sentrux:sentrux-dsm` — view dependencies between modules (visual pendant)
- skill `module-contract` — when creating a new module, recommends a
  CONTEXT.md if there are Gotchas or Key decisions

## What it does NOT do

- Does not create a per-module CONTEXT.md / DECISIONS.md — an agent
  or a human does that by hand from the template.
- Does not edit the ADR body — only the index.
- Does not parse markdown beyond H2 headings — the structure is simple.
