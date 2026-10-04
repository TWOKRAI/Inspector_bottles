---
name: Plan checkboxes must be updated
description: Always mark completed tasks [x] in plan.md after each phase/task, include commit hashes
type: feedback
originSessionId: 94232869-20f7-4636-b47b-ddae61570b64
---

Правило перенесено в `.claude/commands/dev/implement.md` (§4) (2026-10-04).

**Why:** User noticed Phase 0 and Phase 1 were completed but plan.md still showed `[ ]` for all tasks. This breaks traceability and makes it impossible to track progress by looking at the plan.


For multi-phase plans (`plans/<slug>/plan.md`), also create detailed per-phase plan files (`phase3-system-settings.md`, etc.) in the same folder BEFORE starting the phase. These serve as standalone ТЗ for agents and as documentation for the user.
