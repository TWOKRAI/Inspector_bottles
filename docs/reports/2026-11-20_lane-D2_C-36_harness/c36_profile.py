"""Duty of the system-queue _rlock vs child age: sample from the moment ready_event is set, 0.5 s bins, K incarnations."""
import json, os, random, signal, sys, time
import c36_real_child as h
from multiprocess_framework.modules.process_manager_module.core.process_registry import ProcessRegistry
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

if __name__ == "__main__":
    variant, K, T = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
    period = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    evs = h.fresh_events()
    srm = SharedResourcesManager(); cfg = h.make_cfg(variant); srm.register_process(h.NAME, cfg)
    reg = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm, system_stop_event=evs["sys_stop"],
                          system_ready_event=evs["sys_ready"], run_event=evs["run_ev"])
    nb = int(T / 0.5)
    busy = [0] * nb; n = [0] * nb
    for k in range(K):
        p, ready = h.spawn(reg, cfg)
        q = h.queues_of(srm)["system"]
        qd = h.queues_of(srm)["data"]
        t0 = time.monotonic(); nxt = t0
        while (dt := time.monotonic() - t0) < T:
            if period and time.monotonic() >= nxt:  # command traffic into the child (like a probe/introspect stream)
                q.put({"type": "command", "command": "c36.probe", "sender": "c36driver", "data": {}})
                if variant == "cons":
                    qd.put({"type": "data", "sender": "c36driver", "data": {}})
                nxt += period
            time.sleep(random.expovariate(1000.0))
            b = min(int(dt / 0.5), nb - 1)
            busy[b] += not h.lock_free(q._rlock); n[b] += 1
        os.kill(p.pid, signal.SIGKILL); p.join(5)
        reg.remove_process(h.NAME); srm.register_process(h.NAME, cfg, reuse_queues=False)  # fresh queues each time
    print("C36PROFILE", json.dumps({"variant": variant, "incarnations": K, "traffic_period_s": period, "bins_s": 0.5,
          "system_busy_frac_by_age": [round(b / m, 4) if m else None for b, m in zip(busy, n)],
          "samples_by_bin": n}), flush=True)
