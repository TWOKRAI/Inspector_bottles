"""T_hold of one get_nowait() on an empty mp.Queue (acquire(False) -> _poll() -> release), and the real tick of sleep(0.01)."""
import multiprocessing as mp
import statistics
import time
from multiprocess_framework.modules.shared_resources_module.queues.core.reader_gone import ReaderGoneQueue
from queue import Empty

if __name__ == "__main__":
    q = ReaderGoneQueue(maxsize=100)
    lock = q._rlock
    orig_acq, orig_rel = lock.acquire, lock.release
    holds = []
    t_acq = [0.0]

    class L:  # wrap to time exactly acquire->release
        def acquire(self, *a):
            ok = orig_acq(*a)
            t_acq[0] = time.perf_counter()
            return ok

        def release(self):
            holds.append(time.perf_counter() - t_acq[0])
            orig_rel()

    q._rlock = L()
    for _ in range(20000):
        try:
            q.get_nowait()
        except Empty:
            pass
    holds.sort()
    n = len(holds)
    print(f"hold_us n={n} median={holds[n//2]*1e6:.1f} p90={holds[int(n*.9)]*1e6:.1f} p99={holds[int(n*.99)]*1e6:.1f} mean={statistics.mean(holds)*1e6:.1f}")
    ticks = []
    t = time.perf_counter()
    for _ in range(300):
        time.sleep(0.01)
        t2 = time.perf_counter(); ticks.append(t2 - t); t = t2
    print(f"tick_ms median={statistics.median(ticks)*1e3:.2f} mean={statistics.mean(ticks)*1e3:.2f}")
    m = statistics.mean(holds); T = statistics.mean(ticks)
    print(f"predicted duty per queue (idle, no contention) = {m/T*100:.3f} %")
