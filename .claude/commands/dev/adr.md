---
description: Create an ADR in the module's DECISIONS.md (cross-cutting decisions: docs/decisions/). Call when a decision outlives its task and needs a record.
---

# /dev:adr — create an ADR via tech-writer

Launches the tech-writer agent to create a structured ADR
(Architectural Decision Record) based on the current task or the session context.
By default the ADR goes into the module's own `DECISIONS.md`; the global `docs/decisions/`
level is only for decisions that belong to no single module.

## When to use `/dev:adr`

- An **architectural decision** was made (choice of framework, pattern, tool, storage scheme)
- The decision **affects code in multiple places** or future decisions
- You want to record **why** + **alternatives considered** + **consequences**, so the same
  argument doesn't resurface a year later

An ADR is NOT needed for:
- Trivial edits (rename, format, bugfix with no discussion of alternatives)
- Single-file-level decisions that are obvious from the code

## Per-module (default) vs global — where to write

| Decision | Level | Where it lives | Format |
|---------|---------|-----------|--------|
| Within a module, or the module is the main one affected (pattern choice, threading model, API shape) — **default** | Per-module | `<module>/DECISIONS.md`, created from `.claude/plugins/core/templates/DECISIONS.template.md` | `## ADR-{CODE}-NNN` |
| Cross-cutting: touches 2+ modules or the shared stack and belongs to no single module | Global | `docs/decisions/` (see its `README.md`), created from `.claude/plugins/core/templates/ADR.template.md` | per the `docs/decisions/README.md` |

Per-module ADRs are aggregated into `docs/PROJECT_CONTEXT.md` via
`scripts/aggregate_context` (slash-command `/core:quality:sync-context`). Global ADRs
live separately and aren't indexed by this script — they have their own numbering.

If unsure — use the **per-module `DECISIONS.md`**. You can always promote it to the
global level later via a link from the global ADR to the module ADR.

## How it works

1. The command determines the module: from `$ARGUMENTS` (a module name or path) or from the path of the code the decision is about. Then it opens `<module>/DECISIONS.md`; if the file is missing, it is created from `.claude/plugins/core/templates/DECISIONS.template.md` (frontmatter `module_code:`).
2. The next ADR number is the largest NNN among the `##` and `###` `ADR-{CODE}-NNN` headings in that file, plus one (a file can hold `###` ADRs after the last `##` one).
3. It adds a skeleton heading `## ADR-{CODE}-NNN: <title>` after the template's ADR block (date, status `Proposed`, optional `**Refs:**` with the plan path).
4. It passes the tech-writer agent the current task's context + the created skeleton.
5. tech-writer fills in the **Context**, **Decision**, **Alternatives considered**, **Consequences** sections based on the session history and the passed arguments.
6. After the ADR is created, the command reminds the author of the commit trailer: `Decision: ADR-{CODE}-NNN` (one line per id). The commit that adds the ADR heading gets this exact line from the commit hook; a later code commit that implements the ADR carries it too.

Global level (cross-cutting decisions only): the command takes the next number from `docs/decisions/`, fills `ADR.template.md` (`{{NUMBER}}`, `{{TITLE}}`, `{{DATE}}`, `{{AUTHORS}}` — a template for the global level only) and saves it there, status `PROPOSED`.

## Arguments

- `$ARGUMENTS` — a short ADR title (kebab-case or free text), optionally prefixed by the module. Example: `/dev:adr process_manager graceful-gui-close`.

## Workflow recommendation

```
1. The decision was discussed in the session → tech-writer already has the context.
2. /dev:adr <module> <title>   # adds a Proposed ADR to <module>/DECISIONS.md
3. Read the ADR, edit it by hand if needed.
4. Change status to Accepted once agreed.
5. Commit the ADR with `Decision: ADR-<MOD>-NNN`; add the same line to the
   code commits that implement it.
```

## Related commands

- `/dev:spec:spec` — product spec (what the application does for the user), a separate entity from ADR
- `/dev:plan` — task plan, may reference an ADR in the plan's decisions log section
- `tech-writer` (Agent tool) — writes the ADR without the wrapper, if you want more control

## Template

Per-module: `.claude/plugins/core/templates/DECISIONS.template.md` — a `## ADR-{CODE}-NNN` block:
Context, Decision, Alternatives, Consequences.
Global level only: `.claude/plugins/core/templates/ADR.template.md` — structure:
**Context → Decision → Alternatives → Consequences → Implementation pointers → Revisit when**.
