---
name: a-new-plan-must-be-placed-among-its-neighbours
description: A new plan is not done until it is placed among the existing plans of the same area (QUEUE.md + the plans that own adjacent mechanisms) with a two-way link — who owns what, what it takes, what it gives, where the conflict is. Owner's correction 2026-09-22 on gui-service.
metadata:
  type: feedback
  last-verified: 2026-09-22
---

Writing `plans/2026-09-22_gui-service/` I listed frontend-constructor / rework as "neighbouring
plans" in one bullet and moved on. The owner stopped me: "it should be connected somehow with
frontend-constructor, framework-layer-grouping, framework-architecture-rework — whatever is in the
queue about this." Reading those plans changed the new plan in four places: T4.2/T4.4
(`GuiBootstrap`/`GuiHostRuntime`) turned out to be the composition root the Pult must reuse, not
rebuild; `backend-ctl-review-remediation` Ф3 already fixes the very `SocketChannel` diseases I was
about to plan twice; `backend_ctl/AGENTS.md` refuted my "socket bypasses middleware" gap (only the
hub lacks a judge, for everyone); and QUEUE §5 has a standing rule the new plan violates on purpose
(universal code in the prototype) that had to be recorded as an exception.

**Why:** a plan written against the code alone re-plans work that another plan owns, and its
dependencies stay invisible until two teams collide in the same files. The "one active plan per
lane" and "any plan alive longer than a day has a row in QUEUE" rules exist for the same reason.

**How to apply:** before calling a new plan done — (1) `grep` QUEUE.md and `plans/*/plan.md` for
the area's nouns (module names, mechanisms); (2) read what each hit *owns* and write a table
"plan | what it does here | what we take | what we give | boundary/conflict"; (3) put a dated
back-reference *into* each of those plans (a short note, not a rewrite) so the link is two-way;
(4) a standing QUEUE rule the new plan breaks is written down as a recorded exception with a ticket,
not left for the next reconciliation to find. See [[feedback-one-active-plan-per-tool]],
[[feedback-a-plans-premise-expires]].
