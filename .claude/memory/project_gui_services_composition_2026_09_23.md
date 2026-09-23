---
name: gui-services-composition-2026-09-23
description: "Owner's decisions 2026-09-23 on the GUI — recipe and auth are owned by the backend, the Pult is a separate service (apps/pult), the system is split into services and apps are assembled from them; \"do what is architecturally best\"."
metadata:
  node_type: memory
  type: project
  last-verified: 2026-09-23
  originSessionId: 7438de95-7e63-49f8-9fff-ecfe4b75df14
  modified: 2026-09-23T10:40:57.091Z
---

Owner, 2026-09-23, on gui-service: "the recipe belongs to the backend, the frontend only helps edit
it. The Pult is a separate service. Split into services and assemble from them." And, while the plan
was being amended: "above all, do what is architecturally best and correct." Asked whether
`Services/auth` stays a service: yes. Only its host moves (GUI process → backend tree); the code and
the `Services/` layer stay the same.

Recorded in `plans/2026-09-22_gui-service/` rev. 2 (`architecture.md`, `phase-1b-recipe-service.md`,
Task 3.3). The shape: a service is a vertical slice (backend part owns the data + a Qt-free client
port implementation + an optional GUI contribution = `GuiAppSpec`). The host `apps/pult/` loads packs
by name and never imports the prototype (`apps/* ↛ multiprocess_prototype/*` stays without
exception). The target state is one GUI mode, outside the process tree, gated on the Task 1.4 numbers.

**Why:** measured 2026-09-23: the GUI was a fat client. `RecipeManager` is built only in the GUI,
the GUI writes the backend's `app.yaml`, and all 32 `Services.auth` imports sit in the frontend. So a
remote Pult would silently diverge on recipes, and permissions were checked by the party being checked.

**How to apply:** when a GUI feature needs data, add a backend command plus a client port. Never add a
local file read to the GUI. When "cheap now" and "architecturally right" conflict on this track, pick
the right one and write down the cost (the owner said so explicitly). See
[[a-new-plan-must-be-placed-among-its-neighbours]], [[work-order-2026-09-22-line-sim-then-pult]].
