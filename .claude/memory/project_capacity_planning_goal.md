---
name: project-capacity-planning-goal
description: Owner's core goal — observability must turn "doesn't keep up" into sizing requirements (code → language → hardware → more machines) BEFORE the budget is fixed
metadata:
  type: project
---

Owner's principle (2026-09-30, "ЭТО ВАЖНО"): the system and its simulators exist to size a line **before**
hardware is ordered. When inspection does not keep up (e.g. data queue of 50 filling), the system must
produce data that names the weak spot, so the owner can decide in this order:
1. our code / Python is slow → fix or rewrite the hot stage in another language;
2. still short → stronger hardware (CPU/GPU/RAM/camera);
3. still short → split the task across several computers / cameras.
Two computers or extra cameras are easy to justify to management; an under-sized single box that is
already bought and not budgeted is the real failure. Squeeze the maximum out of the current machine first,
but never hide a shortfall.

**Why:** owner is the engineer who commits capacity in the budget up front; simulators (line_sim) exist
exactly to reveal requirements of simple vs hard tasks on given hardware.

**How to apply:**
- Every drop/lag must be counted AND attributed to a stage (transport, queue wait, plugin, send) — a
  bare "dropped N" is not enough; see `plans/transport-single-policy/task-4.5.md` / `task-4.8.md`.
- Classify the limit: one process pinned near 1.0 core → Python/GIL-bound (parallelize or rewrite);
  all cores busy → hardware; copy/bytes dominating → memory bandwidth/transport; camera/NIC → I/O.
- Overflow policy differs by consumer: GUI = latest frame; inspection = every frame, loud
  `not_inspected` on overflow — a silently skipped frame is an uninspected bottle.
- Report numbers as headroom against the frame budget (1/fps), per stage, so they convert into
  "need N cores / 2nd PC" directly.
Related: [[project-hardware-roles-2026-09-23]], [[feedback-cv-threads-tuning]], [[feedback-windows-cpu-psutil-tick-sampled]].
