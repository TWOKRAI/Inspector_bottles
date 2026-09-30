---
name: windows-cpu-psutil-tick-sampled
description: "psutil CPU on Windows is tick-sampled (15.6 ms) and hides phase-locked work by 10-100x; measure with QueryProcessCycleTime"
metadata:
  type: feedback
---

On Windows, measure process/thread CPU with `QueryProcessCycleTime` / `QueryThreadCycleTime` (ctypes, calibrate
GHz on a busy-loop), not psutil `cpu_times`.

**Why:** 2026-09-29, pacing fix 4.3a — the old source loop woke exactly on the 15.6 ms timer tick and the pipeline
finished before the next tick, so psutil charged almost nothing: processor 0.001 core (psutil) vs 0.177 (cycles).
After the fix psutil and cycles agreed (0.207 vs 0.219) and the fix looked like a 10x CPU regression that was not
real. Under constant load (1080p) the gap is only 8-15 %. `time.monotonic` has the same 15.6 ms step on
Python 3.12/Windows — never pace or time sub-20 ms work with it.

**How to apply:** any CPU comparison before/after a timing change on Windows → cycle counters (script
`cpu_truth.py` pattern: harness pids + QueryProcessCycleTime). The permanent backend_ctl CPU metric planned in
Ф4 step 0 must use cycle counters on Windows. Related: [[injection-scripts-on-committed-code]].
