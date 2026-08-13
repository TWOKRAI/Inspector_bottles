---
name: Plan checkboxes must be updated
description: Always mark completed tasks [x] in plan.md after each phase/task, include commit hashes
type: feedback
originSessionId: 94232869-20f7-4636-b47b-ddae61570b64
---
After completing each task or phase from a plan, IMMEDIATELY update the plan file:
- `- [ ]` → `- [x]` for each completed task
- Add commit hash next to the phase commit line
- Add ✅ to the phase header

**Why:** User noticed Phase 0 and Phase 1 were completed but plan.md still showed `[ ]` for all tasks. This breaks traceability and makes it impossible to track progress by looking at the plan.

**How to apply:** After every commit that completes a plan task, update the corresponding checkbox in the plan file. Do this as part of the commit or immediately after. Never defer plan updates to "later". This applies to both Director working directly and agents (developer/teamlead) — the Director must verify and update after agent returns.

For multi-phase plans (`plans/<slug>/plan.md`), also create detailed per-phase plan files (`phase3-system-settings.md`, etc.) in the same folder BEFORE starting the phase. These serve as standalone ТЗ for agents and as documentation for the user.
