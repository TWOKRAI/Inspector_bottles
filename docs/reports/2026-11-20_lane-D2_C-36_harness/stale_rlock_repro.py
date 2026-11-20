"""Stdlib-only: a child with daemon reader threads (get(timeout=0.05)+sleep(0.05), as LifecycleChild._drain)
exits; does the dead child leave the queue's _rlock held?  Prints per-run result and the rate."""

import multiprocessing as mp
import threading
import time


def child(q1, q2, run_s):
    def drain(q):
        while True:
            try:
                q.get(timeout=0.05)
            except Exception:
                time.sleep(0.05)

    for q in (q1, q2):
        threading.Thread(target=drain, args=(q,), daemon=True).start()
    time.sleep(run_s)  # then the process exits with the daemon readers still looping


def free(q):
    ok = q._rlock.acquire(False)
    if ok:
        q._rlock.release()
    return ok


if __name__ == "__main__":
    ctx = mp.get_context("spawn")
    n, stale_any, stale_each = 16, 0, 0
    for i in range(n):
        q1, q2 = ctx.Queue(), ctx.Queue()
        p = ctx.Process(target=child, args=(q1, q2, 1.0 + 0.0137 * i))
        p.start()
        p.join()
        f1, f2 = free(q1), free(q2)
        stale_any += (not f1) or (not f2)
        stale_each += (not f1) + (not f2)
        print(i, "system_free" if f1 else "system_STALE", "data_free" if f2 else "data_STALE", flush=True)
    print(f"runs with >=1 stale reader lock: {stale_any}/{n}; stale locks total {stale_each}/{2 * n}")
