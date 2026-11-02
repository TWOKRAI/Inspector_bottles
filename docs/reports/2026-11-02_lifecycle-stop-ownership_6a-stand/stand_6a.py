# -*- coding: utf-8 -*-
# ruff: noqa: E501
"""stand_6a.py - живой стенд ветки 6а (fix/lifecycle-6a-defects): S9a, S9b (C-64), S10 (C-66), S11 (стоп).

Образец - ``docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/stand_l9.py``: берём оттуда ``Backend`` (свежий
бэкенд со своим портом и конфигами), ``Ctx``, ``send_async``, ``pm_msg``, ``leaf``, ``scan_log_dir``. Наблюдение - только
router-командами backend_ctl: ``wire.setup``, ``wire.status``, ``topology.apply``, ``health.report``, ``health.status``,
``state_get``, ``system.shutdown``; внутренних полей PM скрипт не читает.

Запуск (в окне стенда, PYTHONPATH = корень проверяемого дерева, основной .venv):
    bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" medium inspector-bottles-5e \
        <.venv python> docs/reports/2026-11-02_lifecycle-stop-ownership_6a-stand/stand_6a.py \
        --root <корень дерева> --scenario S9a,S9b,S10 --repeats 3 --out <каталог>
Ожидания (литералы) записаны лидом до прогона; скрипт печатает наблюдённое и сравнивает с ними.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STAND_DIR = HERE.parent / "2026-10-26_lifecycle-stop-ownership_1.9b-stand"
sys.path.insert(0, str(STAND_DIR))

import stand_l9 as L  # noqa: E402  (путь добавлен выше)

CAM, PROC = "cam", "proc"
HEALTH_TARGET = "devices"  # S10: детям стенда команда health.report не доходит (timeout), protected-процесс отвечает
WIRE_KEY = "cam->proc"
STATE_BROKEN = "system.health.broken_wires"
POLL_S = 10.0
SCENARIO_CEILING_S = 60.0


def _procs(extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    base = [
        {"process_name": CAM, "process_class": L.FAST_CLASS},
        {"process_name": PROC, "process_class": L.FAST_CLASS},
    ]
    return {"name": "stand_6a", "processes": base + (extra or []), "wires": []}


def _cmd(
    drv: Any, target: str, command: str, args: dict[str, Any] | None = None, timeout: float = 30.0
) -> dict[str, Any]:
    return L.leaf(drv.send_command(target, command, args or {}, timeout=timeout))


def _find(node: Any, key: str) -> Any:
    """Первое значение ключа ``key`` в произвольно вложенном dict."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            found = _find(v, key)
            if found is not None:
                return found
    return None


def _state(drv: Any, path: str, key: str) -> Any:
    """Значение ``key`` в поддереве ``path`` (router-команда ``state.get_subtree`` в ProcessManager)."""
    try:
        return _find(_cmd(drv, "ProcessManager", "state.get_subtree", {"path": path}, timeout=10.0), key)
    except Exception as exc:  # noqa: BLE001 - наблюдение терпит моргание
        return f"ERR {exc!r}"


def boot_with_wire(ctx: Any, tag: str) -> tuple[Any, Any, dict[str, Any]]:
    """Свежий бэкенд, cam и proc через topology.apply, провод cam->proc (direct) в состоянии active."""
    be = L.Backend(ctx, tag)
    drv = be.start()
    desired = _procs()
    end = time.monotonic() + 60.0
    while True:
        diff = _cmd(drv, "ProcessManager", "topology.diff", {"topology_dict": desired})
        if diff.get("success") is True:
            break
        if time.monotonic() > end:
            raise RuntimeError(f"topology.diff не стал успешным: {diff}")
        time.sleep(0.5)
    res = _cmd(drv, "ProcessManager", "topology.apply", {"topology_dict": desired}, timeout=120.0)
    if res.get("success") is not True:
        raise RuntimeError(f"topology.apply cam/proc: {res}")
    pids = wait_alive(drv, (CAM, PROC))
    time.sleep(1.0)
    setup = _cmd(
        drv,
        "ProcessManager",
        "wire.setup",
        {"wire_key": WIRE_KEY, "source_process": CAM, "target_process": PROC, "transport": "direct"},
    )
    if setup.get("success") is not True:
        raise RuntimeError(f"wire.setup: {setup}")
    st = wire_status(drv)
    if st != "active":
        raise RuntimeError(f"предусловие: wire.status={st!r}")
    return be, drv, {"pids": pids, "setup": setup}


def wait_alive(drv: Any, names: tuple[str, ...], deadline_s: float = 45.0) -> dict[str, int | None]:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        snap = L.Backend.supervision(drv)
        if all(snap.get(n, {}).get("alive") for n in names):
            return {n: snap[n].get("pid") for n in names}
        time.sleep(0.25)
    raise RuntimeError(f"{names} не alive за {deadline_s} с")


def pids_now(drv: Any) -> dict[str, int | None]:
    snap = L.Backend.supervision(drv)
    return {n: snap.get(n, {}).get("pid") for n in (CAM, PROC)}


def wire_status(drv: Any) -> str | None:
    wires = _cmd(drv, "ProcessManager", "wire.status").get("wires") or {}
    return (wires.get(WIRE_KEY) or {}).get("status")


def poll_wire(drv: Any, want: str, deadline_s: float) -> dict[str, Any]:
    """Опрос wire.status каждые 0,25 с: первое наблюдение, время до ``want``, последнее значение."""
    t0 = time.monotonic()
    first = wire_status(drv)
    last, t_want = first, (0.0 if first == want else None)
    while t_want is None and time.monotonic() - t0 < deadline_s:
        time.sleep(0.25)
        last = wire_status(drv)
        if last == want:
            t_want = round(time.monotonic() - t0, 2)
    return {"first": first, "last": last, "t_to_" + want + "_s": t_want}


def poll_broken(drv: Any, want: int, deadline_s: float) -> Any:
    t0 = time.monotonic()
    val = _state(drv, "system.health", "broken_wires")
    while val != want and time.monotonic() - t0 < deadline_s:
        time.sleep(0.5)
        val = _state(drv, "system.health", "broken_wires")
    return val


def apply_bp(drv: Any, bp: dict[str, Any]) -> dict[str, Any]:
    t0 = time.monotonic()
    res = _cmd(drv, "ProcessManager", "topology.apply", {"topology_dict": bp}, timeout=90.0)
    res["_elapsed_s"] = round(time.monotonic() - t0, 2)
    time.sleep(
        1.6
    )  # replace_debounce_s = 1,0 с в orchestrator_config: следующий apply иначе вернёт «debounce cooldown»
    return res


def short(res: dict[str, Any]) -> dict[str, Any]:
    keep = {
        k: res.get(k)
        for k in ("success", "rolled_back", "applied", "error", "message", "unstoppable", "_elapsed_s")
        if k in res
    }
    keep["keys"] = sorted(res.keys())
    return keep


# Варианты настоящего отказа. S9a: до команд (валидация); S9b: после части команд (создание второго процесса не удаётся).
S9A_VARIANTS = {
    "A1_duplicate_name": [{"process_name": CAM, "process_class": L.FAST_CLASS}],
    "A2_wire_to_ghost": "wire",
}
S9B_VARIANTS = {
    "B1_no_such_module": [
        {"process_name": "bad1", "process_class": "no_such_module_6a.Cls"},
        {"process_name": "bad2", "process_class": "no_such_module_6a.Cls"},
    ],
    "B2_no_such_class": [
        {"process_name": "bad1", "process_class": "stand_slow_child.NoSuchClass"},
        {"process_name": "bad2", "process_class": "stand_slow_child.NoSuchClass"},
    ],
}


def run_refused(ctx: Any, rep: int, kind: str, with_shutdown: bool) -> dict[str, Any]:
    variants = S9A_VARIANTS if kind == "S9a" else S9B_VARIANTS
    be = None
    rec: dict[str, Any] = {"scenario": kind, "rep": rep}
    t_start = time.monotonic()
    try:
        be, drv, info = boot_with_wire(ctx, f"{kind.lower()}_r{rep}")
        before = info["pids"]
        rec["pids_before"] = before
        rec["variant"] = None
        for vname, extra in variants.items():
            if extra == "wire":
                bp = _procs()
                bp["wires"] = [{"source": "cam.out", "target": "ghost.in"}]
            else:
                bp = _procs(extra)
            res = apply_bp(drv, bp)
            rec.setdefault("tried", {})[vname] = short(res)
            if res.get("success") is False:
                rec["variant"], rec["response"] = vname, short(res)
                break
            # вариант не отказал: вернуть топологию к базовой и пойти дальше
            apply_bp(drv, _procs())
            wait_alive(drv, (CAM, PROC))
            before = pids_now(drv)
            rec["pids_before"] = before
        if rec["variant"] is None:
            rec["verdict"] = "NOT_COVERED: ни один вариант не дал success False"
            return rec
        rec["wire_poll"] = poll_wire(drv, "active", POLL_S)
        rec["broken_wires"] = poll_broken(drv, 0, POLL_S)
        rec["pids_after"] = pids_now(drv)
        rec["same_pids"] = rec["pids_after"] == before
        if with_shutdown:
            rec["S11"] = shutdown_measure(be, drv)
        rec["elapsed_s"] = round(time.monotonic() - t_start, 1)
        return rec
    except Exception as exc:  # noqa: BLE001 - стенд не должен падать целиком
        rec["error"] = repr(exc)
        return rec
    finally:
        if be is not None:
            be.stop()


def shutdown_measure(be: Any, drv: Any) -> dict[str, Any]:
    snap = L.Backend.supervision(drv)
    pids = [v.get("pid") for v in snap.values() if isinstance(v.get("pid"), int)]
    try:
        from backend_ctl.protocol import _find_payload

        pm_pid = _find_payload(drv.introspect_status("ProcessManager", timeout=5.0), "pid", "process").get("pid")
        if isinstance(pm_pid, int):
            pids.append(pm_pid)
    except Exception:  # noqa: BLE001
        pass
    sd = L.send_async(drv, L.pm_msg("system.shutdown", {"mode": "graceful"}, "command"), 15.0)
    tree_gone = None
    end = sd.t_send + 30.0
    while time.monotonic() < end:
        if be.proc.poll() is not None:
            if not L.pids_alive(pids):
                tree_gone = time.monotonic()
                break
            time.sleep(0.1)
        else:
            time.sleep(0.02)
    survivors = L.pids_alive(pids) if tree_gone is None else []
    if survivors:
        L.kill_pids(survivors)
    if be.proc.poll() is None:
        be.kill()
    scan = L.scan_log_dir(be.log_root)
    return {
        "tree_exit_s": round(tree_gone - sd.t_send, 3) if tree_gone else None,
        "n_pids": len(pids),
        "survivors": survivors,
        "did_not_stop_in": scan["dns"],
    }


def run_s10(ctx: Any, rep: int) -> dict[str, Any]:
    be = None
    rec: dict[str, Any] = {"scenario": "S10", "rep": rep}
    try:
        be, drv, _info = boot_with_wire(ctx, f"s10_r{rep}")

        def snapshot() -> dict[str, Any]:
            h = _cmd(drv, HEALTH_TARGET, "health.status").get("health") or {}
            return {"status": h.get("status"), "degraded_reason": h.get("degraded_reason")}

        def tree_after(want_status: str) -> dict[str, Any]:
            end = time.monotonic() + 8.0
            cur: dict[str, Any] = {}
            while time.monotonic() < end:
                cur = {
                    "status": _state(drv, f"processes.{HEALTH_TARGET}.health", "status"),
                    "degraded_reason": _state(drv, f"processes.{HEALTH_TARGET}.health", "degraded_reason"),
                }
                if cur["status"] == want_status:
                    break
                time.sleep(0.5)
            return cur

        rec["report_degraded"] = _cmd(drv, HEALTH_TARGET, "health.report", {"status": "degraded", "message": "x"})
        rec["snapshot_degraded"] = snapshot()
        rec["tree_degraded"] = tree_after("degraded")
        rec["report_ok"] = _cmd(drv, HEALTH_TARGET, "health.report", {"status": "ok", "message": "ok"})
        rec["snapshot_ok"] = snapshot()
        rec["tree_ok"] = tree_after("ok")
        return rec
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)
        return rec
    finally:
        if be is not None:
            be.stop()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, help="корень дерева под проверкой")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenario", default="S9a,S9b,S10")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--recipe", default=L.DEFAULT_REPO_RECIPE)
    ap.add_argument("--boot-timeout", type=float, default=120.0)
    args = ap.parse_args(argv)
    ns = argparse.Namespace(
        python=args.python, recipe=args.recipe, door="direct", boot_timeout=args.boot_timeout, quick=False
    )
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ctx = L.Ctx(ns, Path(args.root).resolve(), out)
    picked = [s.strip() for s in args.scenario.split(",") if s.strip()]
    results: list[dict[str, Any]] = []
    for rep in range(1, args.repeats + 1):
        for sc in picked:
            if sc == "S9a":
                rec = run_refused(ctx, rep, "S9a", with_shutdown=True)
            elif sc == "S9b":
                rec = run_refused(ctx, rep, "S9b", with_shutdown=False)
            elif sc == "S10":
                rec = run_s10(ctx, rep)
            else:
                continue
            results.append(rec)
            print(json.dumps(rec, ensure_ascii=False, default=str), flush=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
