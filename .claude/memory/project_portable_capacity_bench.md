---
name: project-portable-capacity-bench
description: Owner will run tests and capacity measurements on other hardware (Orin NX Linux ARM, others) — bench must be one repo command, portable, with a machine passport and clock self-check
metadata:
  type: project
---

Owner, 2026-09-30: work happens on the Windows laptop now, but the same tests and measurements must run "fast and
easy" on other hardware later to judge that hardware's performance (line target: Orin NX 16, Linux ARM —
[[project_hardware_roles_2026_09_23]]). This is the delivery form of [[project-capacity-planning-goal]].

**Why:** measurement scripts so far lived in session scratchpads (stand44/46/45.py, the 1080p recipe in a
two-sessions-old temp folder) and the CPU probe is Windows-only (`QueryProcessCycleTime` + registry `~MHz`) —
none of it survives a move to another machine.

**How to apply:**
- Any new measurement script goes into the repo (`scripts/capacity_bench`, Task 4.8a in
  `plans/transport-single-policy/task-4.8.md`), never only into a scratchpad; recipes it uses live in the repo.
- Every report carries a machine passport (CPU, cores, RAM, GPU, OS, commit) and a CPU-clock self-check
  (1 busy core must read 1.0 ± 5 %), because the `~MHz` trick is verified only on the i5-12500H.
- Linux path: per-process CPU from `/proc` (accurate there); no winreg/ctypes imports at module level.
- Follow [[shared-stand-and-tests-protocol]] for the stand worktree, lock and A/B windows.
