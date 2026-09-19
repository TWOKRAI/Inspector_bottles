---
description: Create a new ADR (Architectural Decision Record) in docs/claude/DECISIONS/
---

# /dev:adr — create an ADR via tech-writer

Launches the tech-writer agent to create a structured ADR
(Architectural Decision Record) based on the current task or the session context.

## When to use `/dev:adr` (this command creates a global, cross-module ADR)

- An **architectural decision** was made (choice of framework, pattern, tool, storage scheme)
- The decision **affects code in multiple places** or future decisions
- You want to record **why** + **alternatives considered** + **consequences**, so the same
  argument doesn't resurface a year later
- Touches **2+ modules** or the shared stack (cross-module)

An ADR is NOT needed for:
- Trivial edits (rename, format, bugfix with no discussion of alternatives)
- Single-file-level decisions that are obvious from the code

## Global (`/dev:adr`) vs per-module (`DECISIONS.md`) — where to write

| Decision | Level | Where it lives | Format |
|---------|---------|-----------|--------|
| Touches 2+ modules or the shared stack | Global | `docs/claude/DECISIONS/NNNN-<slug>.md` (created by `/dev:adr`) | `ADR-NNNN` |
| Within a single module (pattern choice, threading model, API shape) | Per-module | `<module>/DECISIONS.md` (created by the agent from `.claude/plugins/core/templates/DECISIONS.template.md`) | `ADR-{CODE}-NNN` |

Per-module ADRs are aggregated into `docs/PROJECT_CONTEXT.md` via
`scripts/aggregate_context` (slash-command `/core:quality:sync-context`). Global ADRs
live separately and aren't indexed by this script — they have their own numbering.

If unsure — start with **per-module DECISIONS.md**. You can always promote it to the
global level later via a link from the global ADR to the module ADR.

## How it works

1. The command determines the next ADR number (from `docs/claude/DECISIONS/NNNN-*.md`).
2. Takes `.claude/plugins/core/templates/ADR.template.md`, substitutes `{{NUMBER}}`, `{{TITLE}}`, `{{DATE}}`, `{{AUTHORS}}`.
3. Passes the tech-writer agent the current task's context + the created skeleton.
4. tech-writer fills in the **Context**, **Decision**, **Alternatives considered**, **Consequences** sections based on the session history and the passed arguments.
5. Saves it to `docs/claude/DECISIONS/NNNN-<slug>.md`, default status `PROPOSED`.

## Arguments

- `$ARGUMENTS` — a short ADR title (kebab-case or free text). Example: `/dev:adr embedded-vector-store-vs-qdrant`.

## Workflow recommendation

```
1. The decision was discussed in the session → tech-writer already has the context.
2. /dev:adr <title>            # creates a PROPOSED ADR
3. Read the ADR, edit it by hand if needed.
4. Change status to ACCEPTED once agreed.
5. In the code/CLAUDE.md/STACK.md, add a reference to the ADR number
   where the rule applies.
```

## Related commands

- `/dev:spec:spec` — product spec (what the application does for the user), a separate entity from ADR
- `/dev:plan` — task plan, may reference an ADR in the plan's decisions log section
- `tech-writer` (Agent tool) — writes the ADR without the wrapper, if you want more control

## Template

See `.claude/plugins/core/templates/ADR.template.md` — structure:
**Context → Decision → Alternatives → Consequences → Implementation pointers → Revisit when**.
