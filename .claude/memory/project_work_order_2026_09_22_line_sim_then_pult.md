---
name: work-order-2026-09-22-line-sim-then-pult
description: "Owner-approved work order (2026-09-22) — merge feat/line-sim at the Ф2 boundary first; line-sim Ф3 engine → Ф5 truth (P-1 numbers); gui-service 1.1 inventory anytime → Ф1 → Ф3 (two backends side by side); defer gui-service Ф2 (network), Qt parts of line-sim (Ф6-in-Pult, Ф7.3) and Ф4 camera until the numbers exist. The truth of line-sim lives on the branch (ред. 3), not in main's working tree."
metadata: 
  node_type: memory
  type: project
  last-verified: 2026-09-24
  originSessionId: feb3ecc5-c27a-407d-b327-22e44d808322
  modified: 2026-09-23T21:36:24.440Z
---

**Order approved by the owner on 2026-09-22** (replaces nothing — it slots gui-service into the
2026-09-09 order "line-sim → observability+otel → robot, framework lane in parallel"):

0. **Merge `feat/line-sim` → `main` at the Ф2 boundary** (same discipline as observability-closure:
   first point where product behaviour changes coherently). The branch is ред. 3 (2026-09-21),
   112 commits ahead, Ф0–Ф2 closed by 13 tasks; `apps/line_sim/` (8766), `Plugins/sim/{robot_host,
   scene_source, mjpeg_sink, pult_web}`, `camera_service` backend `stream`, `BeltDrive`, `ctx.state_proxy`
   on `GenericProcess` (ADR-PM-049), belt web-pult on 8092, two-app stand 8765+8766 — all exist there.
1. **line-sim Ф3 engine (3.1 → 3.1a → 3.2 → 3.3 → 3.4 → 3.5) → Ф5 truth (5.1–5.4)** — this is P-1,
   the "caught / missed / duplicates" numbers; does not depend on the Pult.
2. **gui-service 1.1 inventory — any time** (read-only, no stand, removes the main schedule risk)
   → 1.2 → 1.3 → 1.4 → **Ф3** (N backends; landing point for line-sim Qt parts). 1.2 does NOT wait
   for backend-ctl-review-remediation: its 3.2 was closed on main 2026-08-12 (`8fae4034`,
   ADR-PMM-026, `session_isolation` default ON); 3.1 HOL is an acceptance criterion of 1.4.
3. **line-sim Ф7.1 + 7.2 (HTML editor) after 3.1/3.3.** Deferred until there is a real need or the
   numbers exist: gui-service Ф2 (network + token), line-sim Qt parts (Ф6 in the Pult, Ф7.3),
   line-sim Ф4 camera knobs.

**Progress, verified by git 2026-09-24:** step 0 done (`feat/line-sim` fully in `main`, 0 ahead);
step 1 Ф3 done (3.1–3.6 incl. 3.3a/3.4), Ф5 5.1–5.3 done (5.1b, 5.3a/b too) — left: **5.4** fault
knobs (5.5 DEFERRED). gui-service rev. 2 APPROVED 2026-09-23, 1.1 done (`a20e673f`), next 1.2 / 1b.1,
SocketChannel moved into its Task 1.3a (2026-09-24). `feat/observability-closure` also fully in `main`
(4.4); its 4.3b and the otel tail run as two parallel sessions (handoff 2026-09-23). The plan-file
header of `plans/line-sim/plan.md` still says "идёт Ф1" — stale, trust the per-task [DONE] marks.

**Why:** two sessions worked the same day without seeing each other — one ran a team on
`feat/line-sim` (ред. 3, real code), the other rewrote `plans/line-sim/*` in main's working tree
against ред. 2 and planned gui-service on tasks that do not exist ("line-sim 1.1
`Services/frame_stream`", "1.2 simulator tree"). QUEUE.md claimed "23 tasks, 1 closed; no engine
code" — wrong by 12 tasks. Value-first means: land the code that exists, take the measurable
number (P-1), and let the interface lane start from its cheapest de-risking step.

**How to apply:** treat the branch as the plan of record for line-sim; the 2026-09-22 working-tree
edits (Ф1 rewrite, Ф7, `decisions.md`) are input for a "ред. 4" amendment on the branch, never a
competing plan committed to main (QUEUE решение №13). When touching gui-service, `Services/frame_stream`
is a **promotion** of `mjpeg_sink`'s server (Task 2.1), not a new line-sim task. Before planning
against a neighbour, run `git log main..<its branch>` — QUEUE alone lied here. Related:
[[project-priority-engine-first]], [[project-honest-verdict-2026-09]],
[[a-new-plan-must-be-placed-among-its-neighbours]], [[project-line-sim-vision]].
