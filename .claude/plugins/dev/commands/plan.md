---
description: Run the Manager agent (Opus) — decompose a task and write the spec
---

> Before decomposing, consider `/core:quality:dashboard` first — a one-command
> snapshot of project state (plans, architecture, tests, recent activity) that
> gives the Manager current context cheaply.

Launch the **manager** agent (subagent_type: "manager", model: sonnet).

Pass it:
1. The user's task: $ARGUMENTS
2. Context: "Read CLAUDE.md, study the relevant code, create a plan in `plans/`"
3. If there are existing plans — point to the path

**Slug convention (mandatory for Manager):**
- Format: `kebab-case`, `<domain>-<gist>`, max 40 characters
- Examples: `auth-rbac`, `graph-port-validation`, `phase7-plugin-config`
- **Do not use:** bare counters (PLAN-001)
- A phase number is fine as part of a meaningful name (`phase7-plugin-config`)

**Storage (ISO date always in the name — for chronological lookup):**
- Default root: `plans/` (project root). Always save here unless the user explicitly gives another path.
- **Single plan (one file, no phases):** `plans/YYYY-MM-DD_<slug>.md` — for simple tasks (< 50 lines of spec); still allowed, layout v2 below is the default above that size.
- **Plan layout v2 (default for anything above a small spec):** `plans/YYYY-MM-DD_<slug>/` (folder):
  - `plan.md` — contract only: goal, measurable goals, a one-line task index (`- Task 1.1: <name> [PENDING]`) under the `Порядок выполнения`/"Execution order" heading, gates, a `Budget` section. <!-- lint-language: allow -->
  - `tasks/<id>.md` — one file per task, copied from `PLAN.template.md`'s pointer to `core/templates/TASK.template.md`.
  - `amendments.md` — opening row (date, why the plan opened, task count, budget) before the first commit.
- **Multi-phase plan (legacy, no `tasks/`):** `plans/YYYY-MM-DD_<slug>/` (folder) with `plan.md` (metaplan / overview / phase index) + `phase-1.md`, `phase-2.md`, ... — still discovered by the ledger; layout v2 is the default choice for a NEW plan.
- **Date** — the day the plan was created (when `/dev:plan` was invoked), ISO format.
- **Format choice:** Manager decides by complexity — single-file for a spec under ~50 lines, layout v2 (`tasks/<id>.md` + `amendments.md`) for everything else.

**Plan template:** [`.claude/plugins/core/templates/PLAN.template.md`](../../core/templates/PLAN.template.md) — use its structure (frontmatter + Phase/Task with `[PENDING]`/`[DONE]` + Open questions + Decisions log) as a starting point. Remove sections you don't need, but not the frontmatter.

**Mandatory frontmatter:**
```markdown
# Plan: <название на русском>

- **Slug:** <slug>
- **Дата:** YYYY-MM-DD
- **Статус:** DRAFT
- **Ветка:** (заполняется ниже)
```

After receiving the plan:
1. Read the created file
2. Assess the quality of the decomposition
2a. Run `python3 scripts/plans_ledger.py status --check --plan <plan path>`.
   Non-zero → hand the findings back to `manager` (two rounds at most; a third
   refusal goes to the owner with the findings listed). Never set
   `Plan review: APPROVED` while it exits non-zero; for a plan directory
   finish step 4 with `python3 scripts/plans_ledger.py approve <plan>`.
3. **Launch `reviewer` in `MODE: plan`** (subagent_type: "reviewer", model: opus,
   `run_in_background: false`) on the just-written plan file.
   - `CHANGES REQUESTED` → return the list of findings to `manager` for rework.
     One iteration; the second is fixed by the lead directly; there is no third —
     the plan goes to the owner with the open findings listed, instead of a
     request for approval.
   - `APPROVED` → show the owner the plan summary + verdict + the number from
     checklist item (g) (phase cost estimate) and ask for confirmation.
4. Wait for a "yes" from the owner before creating the branch. Update the
   `Plan review` field in the plan header: `APPROVED <date>` or `CHANGES <n>`
   (n — the number of `CHANGES REQUESTED` iterations). For a plan directory
   (layout v2 or multi-phase with `tasks/`), finish here:
   ```bash
   python3 scripts/plans_ledger.py approve <plan>
   ```
   After `approve`, change the contract only by appending a row to
   `amendments.md` and running `python3 scripts/plans_ledger.py amend <plan>` —
   never edit `plan.md`/`tasks/<id>.md` directly.
5. Determine the branch type by Conventional Commits type:
   - New feature → `feat/<slug>`
   - Refactor → `refactor/<slug>`
   - Bug → `fix/<slug>`
   - Documentation → `docs/<slug>`
6. **Create the branch first, then commit the plan** (order matters: the commit-msg hook requires `Refs:` if the branch `<type>/<slug>` already has `plans/YYYY-MM-DD_<slug>.md`):
   ```bash
   git checkout -b <type>/<slug>
   ```
7. Update the `Ветка:` field in the plan → value `<type>/<slug>`. <!-- lint-language: allow -->
8. **Register the plan in the ledger** `plans/README.md` — the script writes the row, not by hand
   (it takes the branch from the `Ветка:` field, counts tasks and phase itself): <!-- lint-language: allow -->
   ```bash
   python3 scripts/plans_ledger.py add <YYYY-MM-DD_slug>.md --status DRAFT   # single
   python3 scripts/plans_ledger.py add <YYYY-MM-DD_slug> --status DRAFT      # multi-phase
   ```
   The ledger is a single index, so a future session doesn't have to reread every plan.
   (`/dev:ship` closes the plan via `plans_ledger.py close` — archive-on-done.)
9. Commit the plan with self-Refs (give the exact path; `git add plans/` also
   includes the updated ledger):
   ```bash
   # Single plan:
   git add plans/
   git commit -m "docs(plans): создать план <slug>

   Why: зафиксировать план перед реализацией
   Layer: docs
   Refs: plans/YYYY-MM-DD_<slug>.md"

   # Multi-phase plan:
   git add plans/
   git commit -m "docs(plans): создать план <slug> (multi-phase)

   Why: зафиксировать план перед реализацией
   Layer: docs
   Refs: plans/YYYY-MM-DD_<slug>/plan.md"
   ```
   (if the project's `.claude/commit-layers.txt` is empty — skip the `Layer:` line).
   `Refs:` always points to a specific file (`plan.md` or `phase-N.md`), never the folder.
10. Show the user: a brief plan summary + branch name + the first Task for `/dev:implement`
