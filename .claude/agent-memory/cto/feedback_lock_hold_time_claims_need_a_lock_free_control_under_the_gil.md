---
name: lock-hold-time-claims-need-a-lock-free-control-under-the-gil
description: A "write() waits on the lock held by drain()" defect measured by writer-observed latency is confounded by the GIL; require a control with a competitor thread that never touches the lock before accepting the defect or crediting the fix
metadata:
  type: feedback
---

Rule: a performance defect stated as "thread A waits on a lock held by thread B for
O(n)" is accepted only with a control run where the competitor thread does the same
amount of Python work WITHOUT the lock. If the control shows the same tail, the number
measured the GIL handoff, not the lock, and the fix is not credited by that number.

**Why:** Task 3.3 of `observability-closure` (2026-09-06). Two independent
measurements (blind tester: 125.7 us vs 0.32 base; otel track: p99 3.2 -> 118.7 us)
declared `BoundedChannel.drain()` copying under the lock a defect and a deque-swap fix
was scoped in. My bench, HEAD vs fixed, same harness, 20k writes x2 reps: busy
competitor p99 22-24 us (HEAD) vs 21-29 us (fixed) -- indistinguishable; competitor
running pure Python with NO lock: p99 6-10 us, max 120-265 us -- the same tail. The
copy `list(deque)` is a C call that holds the GIL regardless of where the lock is, so
moving it outside the lock cannot make the writer runnable during the copy. The
tester's K-T1(b) test (max <= 50 x 0.28 us) stayed red on the fixed code (95.6 us):
its threshold sits below the normal GIL handoff tail on Windows, so it fails for any
implementation and would only be "fixed" by loosening it into a non-guard.

**How to apply:** in any verdict on a lock/latency claim in this CPython codebase:
(1) ask for the lock-free control; (2) judge the fix by lock hold time measured
inside the critical section, not by writer-observed p99/max; (3) never let a blind
tester assert a wall-clock max under thread contention -- performance criteria are
the lead's stand numbers. Related: [[a-delta-benchmark-hides-what-sits-on-both-sides]].
