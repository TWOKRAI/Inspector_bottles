---
description: Sync the living spec (docs/direction/) with the code — spec-writer + manager → a new plan with Task X.Y
---

**SYNC** mode: the user edited `docs/direction/*.md` → we determine the discrepancies with the
code → generate a task plan to fix them.

Input: $ARGUMENTS — path to the application (e.g. `apps/specs` or `projects/quick_translate`).

## Algorithm

1. **Check the arguments**
   If $ARGUMENTS is empty:
   > Specify the application: `/dev:spec:spec-sync <path>`
   > Example: `/dev:spec:spec-sync apps/specs` or `/dev:spec:spec-sync projects/specs`

2. **Check whether the spec exists**
   - Does the `$ARGUMENTS/docs/direction/` folder exist?
   - Is there at least one `*.md` file?
   - If not → `First create the spec via /dev:spec:spec CREATE $ARGUMENTS`

3. **Call spec-writer in SYNC mode**
   ```
   Agent(subagent_type: "spec-writer", prompt: "SYNC mode for $ARGUMENTS. Read every docs/direction/*.md and compare it with the code. Output a LIST OF DISCREPANCIES — UI elements described in the spec but missing from the code, or the other way round. Format: spec file → what to change in the code.")
   ```

4. **Process the spec-writer result**
   - If there are no discrepancies → `✓ Spec is synced with the code, no tasks needed`
   - If there are discrepancies → hand them to manager for decomposition

5. **Call manager for decomposition**
   ```
   Agent(subagent_type: "manager", prompt: "The user edited docs/direction/ for $ARGUMENTS. Discrepancies:\n\n<spec-writer result>\n\nDecompose into Task X.Y and save the plan to plans/spec-sync.md")
   ```

6. **Report**
   ```
   ✓ Spec analyzed: $ARGUMENTS/docs/direction/
   ✓ Discrepancies found: N
   ✓ Plan created: plans/spec-sync.md
   → Run /dev:pipeline or /dev:implement <task> to implement
   ```

## Typical user flow

```
1. The user edits apps/specs/docs/direction/02_editor.md
   (adds a description of a new "Export to PDF" button)

2. /dev:spec:spec-sync apps/specs
   → spec-writer sees: the button is in the spec, not in the code
   → manager decomposes: Task 1.1 — add a QPushButton, Task 1.2 — the handler, Task 1.3 — PDF export

3. /dev:implement 1.1 → /dev:implement 1.2 → /dev:implement 1.3
   or /dev:pipeline end to end
```

## When NOT to call it

- First-time spec creation for the application → `/dev:spec:spec CREATE <app>`
- Code-only changes (spec untouched) → `/dev:spec:spec UPDATE <app>`
- A small, targeted spec change → simpler to go straight to `/dev:plan "<description>"` without
  spec-sync

## Boundary with /dev:spec:spec

| Command | Mode | Direction |
|---------|------|-----------|
| `/dev:spec:spec CREATE <app>` | CREATE | code → spec (first-time creation) |
| `/dev:spec:spec UPDATE <app>` | UPDATE | code → spec (after code changes) |
| `/dev:spec:spec-sync <app>` | SYNC | spec → code (user edited the spec) |
