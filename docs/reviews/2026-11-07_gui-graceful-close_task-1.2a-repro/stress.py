"""Stress: command thread + root thread + status pollers + force escalation, daemon threads with join deadline."""
import threading, time, random
from multiprocess_framework.modules.process_manager_module.tests.test_supervision_status_system_stop import _Light

bad = 0
for it in range(300):
    lt = _Light()
    pm = lt.pm
    errs = []
    def wrap(fn):
        def run():
            try: fn()
            except BaseException as e: errs.append(repr(e))
        return run
    def cmd():
        pm._cmd_system_shutdown({"_sender": "gui"})
        pm._cmd_system_shutdown({"mode": "force", "deadline_s": 0.5})
    def root():
        lt.cs.request_stop(); lt.cs.join_until(time.monotonic() + 1); lt.cs.close()
    def poll():
        for _ in range(200):
            s = pm._cmd_supervision_status()["system_stop"]
            assert s is None or set(s) == {"phase","mode","initiator","started_at","deadline_at","pre_stop_step"}, s
    ths = [threading.Thread(target=wrap(f), daemon=True) for f in (cmd, root, poll, poll)]
    random.shuffle(ths)
    for t in ths: t.start()
    for t in ths: t.join(10)
    alive = [t for t in ths if t.is_alive()]
    if alive or errs:
        bad += 1
        print("iteration", it, "alive", len(alive), "errs", errs[:2])
    else:
        snap = pm._system_stop_snapshot()
        sw = lt.store.stop_writes()
        if snap["phase"] != "done" or sw.get("system.stop.phase") != "done":
            bad += 1; print("iteration", it, "phase in dict", snap["phase"], "in store", sw.get("system.stop.phase"))
print("iterations 300, bad =", bad)
