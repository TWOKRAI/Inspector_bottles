---
name: a-new-plan-must-be-placed-among-its-neighbours
description: A new plan is not done until it is placed among the existing plans of the same area (QUEUE.md + the plans that own adjacent mechanisms) with a two-way link — who owns what, what it takes, what it gives, where the conflict is. Owner's correction 2026-09-22 on gui-service.
metadata:
  type: feedback
  last-verified: 2026-09-22
---

Правило перенесено в `.claude/commands/dev/plan.md` (шаг 4) и агент `manager` (2026-10-04).

**Why:** a plan written against the code alone re-plans work that another plan owns, and its
dependencies stay invisible until two teams collide in the same files. The "one active plan per
lane" and "any plan alive longer than a day has a row in QUEUE" rules exist for the same reason.
