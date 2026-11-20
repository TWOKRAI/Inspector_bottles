"""C-36: real GenericProcess child (real runner, real SystemThreads/RouterManager/QueueChannel, real DataReceiver),
spawned through the real ProcessRegistry on real ReaderGoneQueue queues (DEFAULT_QUEUES), killed at a random moment.

modes:
  duty  -- no kills: sample q._rlock.acquire(False) from the parent at random moments -> P(lock held) per queue
  kill  -- cycles: spawn -> deaf-probe (put 3 commands, are bytes still in the pipe after 0.6 s?) -> random wait -> signal
           -> probe _rlock/_wlock of every queue of the dead child -> restart (reuse or fresh queues, PM order)
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import random
import signal
import sys
import time

from multiprocess_framework.modules.process_manager_module.core.process_registry import ProcessRegistry
from multiprocess_framework.modules.process_module.configs.process_launch_config import DEFAULT_QUEUES
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

GP = "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess"
NAME = "c36child"


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def lock_free(lock):
    if lock is None:
        return None
    ok = lock.acquire(False)
    if ok:
        lock.release()
    return ok


def make_cfg(variant):
    plugins = []
    if variant in ("idle", "cam"):
        plugins.append({"plugin_class": "c36_plugins.C36Source", "plugin_name": "c36_src"})
    if variant == "cons":
        plugins.append({"plugin_class": "c36_plugins.C36Proc", "plugin_name": "c36_proc"})
    return {
        "queues": {k: dict(v) for k, v in DEFAULT_QUEUES.items()},
        "config": {"plugins": plugins, "chain_targets": [], "source_target_fps": 100.0},
    }


def queues_of(srm):
    return dict(srm.queue_registry.get_process_queues(NAME))


def drain_like_pm(srm):
    """Mirror of ProcessManagerProcess._drain_process_queues (get_nowait until any exception)."""
    n = 0
    for q in queues_of(srm).values():
        for _ in range(10_000):
            try:
                q.get_nowait()
                n += 1
            except Exception:  # noqa: BLE001 - same as PM: Empty (or a busy _rlock!) ends the drain silently
                break
    return n


def deaf_probe(q, qtype, n=3, wait=0.6):
    """put n messages; True = bytes are still in the pipe after `wait` s (nobody read them)."""
    for i in range(n):
        if qtype == "system":
            q.put({"type": "command", "command": "c36.probe", "sender": "c36driver", "data": {"i": i}})
        else:
            q.put({"type": "data", "sender": "c36driver", "data": {"i": i}})
    time.sleep(wait)
    return bool(q._reader.poll(0))


def fresh_events():
    evs = {"sys_stop": mp.Event(), "sys_ready": mp.Event(), "run_ev": mp.Event()}
    evs["sys_ready"].set()
    evs["run_ev"].set()
    return evs


def install_events(reg, evs):
    reg._system_stop_event = evs["sys_stop"]
    reg._system_ready_event = evs["sys_ready"]
    reg._run_event = evs["run_ev"]


def ev_locks_free(evs):
    return {k: lock_free(ev._cond._lock) for k, ev in evs.items()}


def spawn(reg, cfg, wait_s=10.0):
    p = reg.create_and_register(NAME, GP, cfg)
    p.start()
    ready = reg.get_ready_event(NAME).wait(wait_s)
    if not ready:  # hung incarnation: dump its Python stacks (PYTHONFAULTHANDLER=1) before it is killed
        print(f"C36HUNG pid={p.pid} -> SIGABRT for faulthandler stacks", flush=True)
        os.kill(p.pid, signal.SIGABRT)
        p.join(5)
    return p, ready


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["duty", "kill"])
    ap.add_argument("--variant", choices=["idle", "cam", "cons"], default="idle")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--kills", type=int, default=50)
    ap.add_argument("--budget", type=float, default=280.0, help="wall-clock cap, s")
    ap.add_argument("--reuse", type=int, default=1)
    ap.add_argument("--sig", choices=["KILL", "TERM"], default="KILL")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    evs = fresh_events()
    sys_stop, sys_ready, run_ev = evs["sys_stop"], evs["sys_ready"], evs["run_ev"]
    srm = SharedResourcesManager()
    cfg = make_cfg(a.variant)
    srm.register_process(NAME, cfg)
    reg = ProcessRegistry(queue_registry=srm.queue_registry, shared_resources=srm, system_stop_event=sys_stop,
                          system_ready_event=sys_ready, run_event=run_ev)
    out = open(a.out, "a") if a.out else None

    def emit(rec):
        line = json.dumps(rec, ensure_ascii=False)
        print("C36", line, flush=True)
        if out:
            out.write(line + "\n")
            out.flush()

    t0 = time.monotonic()
    if a.mode == "duty":
        p, ready = spawn(reg, cfg)
        time.sleep(1.0)
        qs = queues_of(srm)
        busy = {k: 0 for k in qs}
        ebusy = {k: 0 for k in evs}
        n = 0
        end = time.monotonic() + a.seconds
        while time.monotonic() < end:
            time.sleep(random.expovariate(1000.0))
            for k, q in qs.items():
                busy[k] += not lock_free(q._rlock)
            for k, ev in evs.items():
                ebusy[k] += not lock_free(ev._cond._lock)
            n += 1
        os.kill(p.pid, signal.SIGKILL)
        p.join(5)
        res = {"mode": "duty", "variant": a.variant, "burn_ms": os.environ.get("C36_BURN_MS", "0"), "ready": ready,
               "samples": n}
        for k in qs:
            lo, hi = wilson(busy[k], n)
            res[k] = {"busy": busy[k], "frac": round(busy[k] / n, 5), "wilson95": [round(lo, 5), round(hi, 5)]}
        res["event_cond_lock_busy"] = {k: [v, round(v / n, 5)] for k, v in ebusy.items()}
        emit(res)
        return

    sig = signal.SIGKILL if a.sig == "KILL" else signal.SIGTERM
    inherited = set()  # qtypes whose _rlock was already busy BEFORE this incarnation was spawned (reused dead queue)
    tot = {"kills": 0, "deaf_checked": 0, "deaf": 0, "deaf_after_stuck": 0, "checked_after_stuck": 0,
           "deaf_after_free": 0, "checked_after_free": 0, "resets": 0, "hung": 0}
    stuck_cnt = {}
    wstuck_cnt = {}
    i = 0
    while i < a.kills and time.monotonic() - t0 < a.budget:
        p, ready = spawn(reg, cfg)
        qs = queues_of(srm)
        rec = {"i": i, "pid": p.pid, "ready": ready, "inherited_stuck": sorted(inherited),
               "queue_ids": {k: id(q) for k, q in qs.items()}}
        if i > 0 and ready:
            deaf = {"system": deaf_probe(qs["system"], "system")}
            if a.variant == "cons":
                deaf["data"] = deaf_probe(qs["data"], "data")
            rec["deaf"] = deaf
            any_deaf = any(deaf.values())
            tot["deaf_checked"] += 1
            tot["deaf"] += any_deaf
            if inherited:
                tot["checked_after_stuck"] += 1
                tot["deaf_after_stuck"] += any_deaf
            else:
                tot["checked_after_free"] += 1
                tot["deaf_after_free"] += any_deaf
        time.sleep(random.uniform(0.15, 0.9))
        os.kill(p.pid, sig)
        p.join(5)
        rec["exitcode"] = p.exitcode
        tot["kills"] += 1
        rl = {k: lock_free(q._rlock) for k, q in qs.items()}
        wl = {k: lock_free(getattr(q, "_wlock", None)) for k, q in qs.items()}
        rec["rlock_free"] = rl
        rec["wlock_free"] = wl
        el = ev_locks_free(evs)
        rec["event_lock_free"] = el
        ev_stuck = [k for k, v in el.items() if v is False]
        for k in ev_stuck:
            tot["event_lock_stuck_" + k] = tot.get("event_lock_stuck_" + k, 0) + 1
        if ev_stuck or not ready:
            evs = fresh_events()  # keep later kills independent of an absorbed shared Event
            install_events(reg, evs)
            rec["events_replaced"] = True
        tot["hung"] += (not ready)
        newly = [k for k, v in rl.items() if v is False and k not in inherited]
        rec["newly_stuck"] = newly
        for k in newly:
            stuck_cnt[k] = stuck_cnt.get(k, 0) + 1
        for k, v in wl.items():
            if v is False:
                wstuck_cnt[k] = wstuck_cnt.get(k, 0) + 1
        reg.remove_process(NAME)
        if a.reuse and not inherited:
            srm.register_process(NAME, cfg, reuse_queues=True)  # PM order: register(reuse) -> drain
            rec["drained"] = drain_like_pm(srm)
            rec["restart"] = "reuse"
            inherited = set(newly)
        else:
            srm.register_process(NAME, cfg, reuse_queues=False)  # fresh queues (control a, or reset after a dead queue)
            rec["restart"] = "fresh"
            if a.reuse:
                tot["resets"] += 1
            inherited = set()
        emit(rec)
        i += 1
    res = {"mode": "kill", "variant": a.variant, "burn_ms": os.environ.get("C36_BURN_MS", "0"), "reuse": a.reuse,
           "sig": a.sig, "wall_s": round(time.monotonic() - t0, 1), **tot,
           "rlock_stuck_after_kill": stuck_cnt, "wlock_stuck_after_kill": wstuck_cnt}
    for k, v in stuck_cnt.items():
        res[f"wilson95_{k}"] = [round(x, 4) for x in wilson(v, tot["kills"])]
    res["wilson95_system_if0"] = [round(x, 4) for x in wilson(stuck_cnt.get("system", 0), tot["kills"])]
    emit({"summary": res})


if __name__ == "__main__":
    main()
