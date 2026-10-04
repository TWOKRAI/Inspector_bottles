---
name: observability-knobs-switchable-at-any-boundary-zero-cost-off
description: Owner's standing rule 2026-09-08 — every observability parameter must be switchable on/off at any boundary (process, hop, sink, metric) at runtime for debugging, viewable on demand, and cost nothing when off; measured gaps — sink disable still pays emission, frame_trace is import-time only
metadata:
  type: feedback
---

Правило перенесено в `.claude/skills/project-rules/SKILL.md` §5 (ADR модуля — Task 4.15, ещё не написан) (2026-10-04).

**Why:** the owner's use is debugging a live line: switch a boundary on, look, switch it off, and trust that
the production path is untouched. A knob whose OFF still pays emission silently steals the frame budget.
