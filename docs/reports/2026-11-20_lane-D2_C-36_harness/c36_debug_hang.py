"""Spawn real child, kill -9, respawn on the same shared objects, SIGABRT the hung incarnation -> faulthandler stacks."""
import os, signal, sys, time
import c36_real_child as h
import multiprocessing as mp
from multiprocess_framework.modules.process_manager_module.core.process_registry import ProcessRegistry
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

if __name__ == "__main__":
    variant = sys.argv[1]
    sys_stop, sys_ready, run_ev = mp.Event(), mp.Event(), mp.Event()
    sys_ready.set(); run_ev.set()
    srm = SharedResourcesManager(); cfg = h.make_cfg(variant); srm.register_process(h.NAME, cfg)
    reg = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm, system_stop_event=sys_stop,
                          system_ready_event=sys_ready, run_event=run_ev)
    p, ready = h.spawn(reg, cfg); print("DBG inc0 ready", ready, flush=True)
    time.sleep(0.5); os.kill(p.pid, signal.SIGKILL); p.join(5)
    for nm, ev in (("sys_stop", sys_stop), ("sys_ready", sys_ready), ("run_ev", run_ev)):
        print("DBG event", nm, "cond_lock_free", h.lock_free(ev._cond._lock), flush=True)
    reg.remove_process(h.NAME); srm.register_process(h.NAME, cfg, reuse_queues=False)
    p, ready = h.spawn(reg, cfg) if False else (None, None)
    p = reg.create_and_register(h.NAME, h.GP, cfg); p.start()
    ok = reg.get_ready_event(h.NAME).wait(8); print("DBG inc1 ready", ok, flush=True)
    if not ok:
        os.kill(p.pid, signal.SIGABRT); p.join(5)
    else:
        os.kill(p.pid, signal.SIGKILL); p.join(5)
