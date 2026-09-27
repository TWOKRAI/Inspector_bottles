---
name: build-from-framework-as-constructor
description: "Owner's standing rule 2026-09-27 — every app (the simulator included) is assembled from the framework and existing tools as a constructor: processes, workers, router, recipe/state modules; the frontend is a constructor too. Search for the ready mechanism before writing one."
metadata:
  node_type: memory
  type: feedback
  last-verified: 2026-09-27
  originSessionId: 4dc1454e-7dba-4d63-9579-e99bc22cf8b6
  modified: 2026-09-27T18:59:14.011Z
---

Owner, 2026-09-27: "take as a rule — use the ready tools and the framework as a constructor. The
simulator must also use processes, workers, the router and so on. The frontend will be a constructor
too, account for it."

**Why:** measured the same day on line-sim-layer-editor Task 1.2a — I briefed "modelled on
`recipe.*`" instead of "take it from `recipe`", and the teamlead re-implemented rev + atomic write
while `multiprocess_framework/modules/recipe` already had `compute_rev`, `_atomic_write` (with fsync —
ours had none, a review finding) and `yaml_io.update_yaml_preserving` (keeps comments — ours wiped 38
comment lines, another review finding). Two review findings were the price of not looking.

**How to apply:**
- Before a brief's DESIGN, grep `multiprocess_framework/modules/*` and `Services/*` for the mechanism
  (rev/CAS, atomic write, threads -> `worker_module`, long work -> a separate process + router,
  state -> `state_store_module`) and write "reuse X" into DESIGN, not "modelled on X".
- Work that must not block a thread goes to a process/worker of the framework, not an ad-hoc
  `threading.Thread` inside a plugin.
- A framework piece that is almost right is fixed IN the framework (e.g. made `update_yaml_preserving`
  atomic) — then every consumer gains; not copied beside it.
- GUI work: no hand-made windows/forms in apps; the editor's Qt part goes through the widget
  constructor (`sim.*` pack) — see [[gui-constructor-layers-2026-09-26]].
