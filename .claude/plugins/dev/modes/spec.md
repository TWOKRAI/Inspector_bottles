# Spec Mode — Living Product Specification

Loaded for tasks: create/update a product specification, describe an application from the user's perspective, synchronize a spec with the code.

> **Before starting** read `.claude/modes/_stack.md` — the "Specs" section tells you where spec files are stored in this project.

## Philosophy

A **living spec** is a product specification that the user edits as an instruction for Claude. It is not technical code documentation — it describes application behavior from the user's perspective.

Cycle:
```
spec-writer creates/updates spec files
↓
User reads and edits (this is the user interface to the code)
↓
/dev:spec:spec-sync → manager compares spec vs code → Task X.Y in plans/
↓
/dev:pipeline or /dev:implement → code is brought into alignment with spec
```

## Agents

| Agent | Skill | Purpose |
|-------|-------|---------|
| **spec-writer** (Sonnet 4.6) | `/dev:spec:spec` | Create / update spec files |
| **manager** (Sonnet 4.6) | `/dev:spec:spec-sync` | Compare spec with code → decompose → Task X.Y |

## Typical spec file structure

Depends on project type (see `_stack.md` → "Specs"). Typical templates:

**Single-app project:**
```
docs/direction/
  00_INDEX.md         — Table of contents, version, instructions
  01_layout.md        — Main window / structure
  02_<feature>.md     — Features and screens
```

**Multi-app project (e.g., apps/):**
```
apps/<app>/docs/direction/
  00_INDEX.md
  01_layout.md
  02_<feature>.md
  ...
```

Each file contains YAML frontmatter + markdown. It describes WHAT the user sees and HOW they interact, not how things are implemented internally.

## Typical scenarios

```
New application, designing UX         →  /dev:spec:spec [<app>]  → spec-writer creates skeleton
User wants to change UX               →  edit spec  →  /dev:spec:spec-sync [<app>]  →  manager → Task
Sync after a major refactor           →  /dev:spec:spec-sync [<app>]
Understand what should be in project  →  read [docs/direction|apps/X/docs/direction]/00_INDEX.md
```

## Rules

1. **Spec is the source of truth for UX** — when spec conflicts with code, spec wins (unless the user explicitly says otherwise)
2. **No technical implementation in spec** — do not mention classes, functions, or DB schemas. Behavior only
3. **Language** — see `_stack.md` (section "Language policy")
4. **Versioning via 00_INDEX.md** — every update changes `version:` in frontmatter and appends a changelog entry
5. **Spec lives alongside the application** (for multi-app) or at the root `docs/direction/` (for single-app)
