---
name: project_graceful_stop_debt
description: PM 5 s stop hang (L-2) — real cause is interpreter exit waiting on mp.Queue feeders; two sources, one fixed (EventManager), one open (writer outlives reader); what is refuted and what was rejected
metadata:
  type: project
  last-verified: 2026-09-23
---

**Symptom:** `spawner: ProcessManager did not stop in 5.0s, terminating...` on system stop; PM killed.

**Real mechanism (dump-verified 2026-09-23, faulthandler + `sample`):** all children and the PM finish
teardown in ~0.6 s; then CPython's `multiprocessing.util._exit_function → _finalize_join` waits for the
feeder thread of an `mp.Queue` the process wrote to, blocked in `send_bytes` on a full pipe nobody drains.
No EPIPE ever comes: every process that received the queue keeps its read end open.

**Two sources:**
1. `EventManager._event_queue` — an `mp.Queue` with no reader (only `wait_for_event`, unused outside tests).
   FIXED: process-local bounded `queue.Queue(1000)`, ADR-SRM-015 (`plans/lifecycle-graceful-stop.md` Task 1.1).
2. Writer outlives reader at stop: all processes stop in parallel; `renderer` still sends a frame into
   `gui/data` after `gui` exited; the message does not fit the pipe. OPEN — Task 1.2 of the same plan.
   The live stop is still 5.5 s in 4 of 5 runs until it lands.

**Refuted (do not re-chase):** the June hypothesis "source worker blocks in `produce()`" — workers stop in
10–50 ms today, and the PM (which has no `produce()`) is the one that hangs. `BatchBuffer` no longer exists.

**Rejected fix:** generic release of feeders at exit (`cancel_join_thread` / `Finalize.cancel` / private
`_finalizer_registry`) under a short budget. It truncates a message mid-write to a slow LIVE reader
(15/100 delivered, the reader hangs forever in `os.read`). A writer cannot tell a dead reader from a slow one
by wall time — any release must be keyed on an explicit "reader gone" signal.

**Why orphans survive (L-5, separate):** `ProcessTreeGuard` group kill is a no-op on the normal path, the
spawner and PM budgets are both 5.0 s, and `BackendHarness` snapshots the subtree before children exist. An
orphan keeps the caller's stdout open, so wrapper scripts look "hung > 300 s".

**How to apply:** when a stop takes ~5 s, dump Python stacks at stop+2.5 s (SIGUSR1 + faulthandler via a
`sitecustomize` on PYTHONPATH) and look for `_finalize_join`; find which queue's feeder is stuck and who
should be reading it. Related: [[project_switch_routing_stale]], [[feedback_fix_framework_forward]].
