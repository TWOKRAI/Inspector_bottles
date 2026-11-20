"""kill0 -> reuse(+drain) inc1 -> SIGABRT if hung -> fresh inc2 -> SIGABRT if hung. faulthandler stacks go to stderr."""
import os, signal, sys, time
import c36_real_child as h
import multiprocessing as mp
from multiprocess_framework.modules.process_manager_module.core.process_registry import ProcessRegistry
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

def ev_state(tag, evs):
    print("DBG", tag, {nm: h.lock_free(ev._cond._lock) for nm, ev in evs.items()}, flush=True)

if __name__ == "__main__":
    evs = {"sys_stop": mp.Event(), "sys_ready": mp.Event(), "run_ev": mp.Event()}
    evs["sys_ready"].set(); evs["run_ev"].set()
    srm = SharedResourcesManager(); cfg = h.make_cfg(sys.argv[1]); srm.register_process(h.NAME, cfg)
    reg = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm, system_stop_event=evs["sys_stop"],
                          system_ready_event=evs["sys_ready"], run_event=evs["run_ev"])
    p, ready = h.spawn(reg, cfg); print("DBG inc0 ready", ready, flush=True)
    time.sleep(0.5); os.kill(p.pid, signal.SIGKILL); p.join(5)
    print("DBG after kill0 rlock_free", {k: h.lock_free(q._rlock) for k, q in h.queues_of(srm).items()}, flush=True)
    ev_state("after kill0 event cond locks free", evs)
    for phase, reuse in (("inc1", True), ("inc2", False)):
        reg.remove_process(h.NAME); srm.register_process(h.NAME, cfg, reuse_queues=reuse)
        if reuse:
            print("DBG drained", h.drain_like_pm(srm), flush=True)
        p = reg.create_and_register(h.NAME, h.GP, cfg); p.start()
        ok = reg.get_ready_event(h.NAME).wait(8); print("DBG", phase, "reuse", reuse, "ready", ok, flush=True)
        if not ok:
            print("DBG ---- stacks of", phase, "pid", p.pid, flush=True)
            os.kill(p.pid, signal.SIGABRT)
        else:
            os.kill(p.pid, signal.SIGKILL)
        p.join(5)
        ev_state(f"after {phase} event cond locks free", evs)
