# ruff: noqa  # артефакт замера 2026-10-03: код сохранён как есть, им сняты числа отчёта; переносится в scripts/stand_gate (Task 5.6)
"""Стенд 4.7d-5: один кейс. Запуск: cwd = PYTHONPATH = меряемое дерево.

python stand47d.py --overflow every --secs 30 --out case.json [--reject-delay 0] [--pause-secs 0] [--port 8775]
"""

import argparse
import json
import os
import re
import statistics
import tempfile
import time
from pathlib import Path
import yaml

for k in [k for k in os.environ if k.startswith("FW_SHM_")]:
    del os.environ[k]

WARMUP_S = 10
PROCS = ["camera_0", "processor", "renderer", "inspector", "storage", "gui"]
EVERY_PROCS = ("processor", "inspector")
CYC_KEYS = (
    "lag_dropped_items",
    "lag_dropped_total",
    "not_inspected_lag",
    "not_inspected_stale_restore",
    "not_inspected_stale_exec",
    "not_inspected_handled",
    "queue_wait_ms",
    "effective_hz",
    "cycles",
)
RS_KEYS = (
    "frame_stale_drops",
    "frame_torn_reads",
    "frame_restore_failures",
    "door_drops",
    "not_inspected_door",
    "queue_data_evicted",
    "frame_loan_exhausted",
    "errors_delivery_failed",
    "deferred_closes",
)


def render(tree: Path, out_dir: Path, overflow: str, reject_delay: int, transit: int) -> Path:
    r = yaml.safe_load((tree / "scripts/capacity_bench/recipes/stand.yaml").read_text(encoding="utf-8"))
    for p in r["processes"]:
        name = p["process_name"]
        for pl in p.get("plugins") or []:
            cls = str(pl.get("plugin_class", ""))
            if cls.endswith("CameraServicePlugin"):
                pl["resolution_width"], pl["resolution_height"] = 1920, 1080
                p["source_target_fps"] = 100
            if cls.endswith("RobotControlPlugin"):
                pl["reject_delay_ms"] = reject_delay
                if transit:
                    pl["transit_ms"] = transit
            if "db_path" in pl:
                pl["db_path"] = str(out_dir / Path(pl["db_path"]).name)
        if overflow == "every" and name in EVERY_PROCS:
            p.setdefault("extras", {})["overflow"] = "every"
    obs = r.setdefault("observability", {}).setdefault("processes", {}).setdefault("inspector", {})
    obs["events"] = {"first_n": 1, "every_mth": 1}
    out = out_dir / f"stand47d_{overflow}.yaml"
    out.write_text(yaml.safe_dump(r, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


def _payload(resp):
    """Ответ драйвера бывает обёрнут; ищем dict с ключом workers/router_stats."""
    if isinstance(resp, dict):
        for key in ("workers", "router_stats"):
            if key in resp:
                return resp
        for v in resp.values():
            got = _payload(v)
            if got is not None:
                return got
    return None


def snap(drv, procs):
    out = {}
    for name in procs:
        rec = {"workers": {}, "rs": {}}
        try:
            st = _payload(drv.introspect_status(name)) or {}
            for wn, ws in (st.get("workers") or {}).items():
                if isinstance(ws, dict):
                    rec["workers"][wn] = {k: ws[k] for k in CYC_KEYS if k in ws}
                    rec["workers"][wn]["_keys"] = sorted(k for k in ws if "inspect" in k or "lag" in k)
            rs = (_payload(drv.introspect_router_stats(name)) or {}).get("router_stats") or {}
            rec["rs"] = {k: rs[k] for k in RS_KEYS if k in rs}
            rec["rs_all"] = {k: v for k, v in rs.items() if isinstance(v, (int, float)) and v}
            q = _payload(drv.introspect_queues(name)) if hasattr(drv, "introspect_queues") else None
            rec["queues"] = drv.introspect_queues(name)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
        out[name] = rec
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overflow", choices=("latest", "every"), required=True)
    ap.add_argument("--secs", type=float, default=30)
    ap.add_argument("--reject-delay", type=int, default=0)
    ap.add_argument("--transit-ms", type=int, default=0)
    ap.add_argument("--pause-secs", type=float, default=0)
    ap.add_argument("--port", type=int, default=8775)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    from backend_ctl.harness import BackendHarness

    case_dir = Path(tempfile.mkdtemp(prefix=f"s47d_{a.overflow}_"))
    log_dir = case_dir / "logs"
    log_dir.mkdir()
    recipe = render(Path.cwd(), case_dir, a.overflow, a.reject_delay, a.transit_ms)
    res = {
        "overflow": a.overflow,
        "secs": a.secs,
        "reject_delay_ms": a.reject_delay,
        "transit_ms": a.transit_ms,
        "case_dir": str(case_dir),
    }
    h = BackendHarness(recipe=recipe, port=a.port, ready_timeout=90, log_dir=log_dir)
    t_boot = time.perf_counter()
    drv = h.start()
    res["start_s"] = round(time.perf_counter() - t_boot, 2)
    try:
        t_ready = time.perf_counter()
        first = None
        while time.perf_counter() - t_ready < 5:
            try:
                st = _payload(drv.introspect_status("camera_0")) or {}
                cyc = sum(
                    int(ws.get("cycles") or 0) for ws in (st.get("workers") or {}).values() if isinstance(ws, dict)
                )
            except Exception:  # noqa: BLE001
                cyc = 0
            if cyc > 0:
                first = round(time.perf_counter() - t_ready, 3)
                break
            time.sleep(0.02)
        res["first_frame_after_ready_s"] = first
        time.sleep(max(0.0, WARMUP_S - (time.perf_counter() - t_ready)))
        res["s0"] = snap(drv, PROCS)
        t0 = time.perf_counter()
        hz = {p: [] for p in PROCS}
        paused = None
        while time.perf_counter() - t0 < a.secs:
            if a.pause_secs and paused is None and time.perf_counter() - t0 > 5:
                paused = pause_executor(drv, res, a.pause_secs)
            ov = drv.system_overview(timeout=5)
            for p in PROCS:
                v = ov.get("processes", {}).get(p, {}).get("hz")
                if isinstance(v, (int, float)):
                    hz[p].append(float(v))
            time.sleep(2)
        res["window_s"] = round(time.perf_counter() - t0, 2)
        res["s1"] = snap(drv, PROCS)
        res["rc_s1"] = _rc(drv)
        res["hz_median"] = {p: (statistics.median(v) if v else None) for p, v in hz.items()}
        # Тишина: камера на паузу, ждём, пока счётчики перестанут меняться — формула на итогах точная.
        res["camera_before_pause"] = snap(drv, ["camera_0"])["camera_0"]
        res["camera_pause"] = drv.send_command("camera_0", "worker.pause_all", timeout=10)
        res["camera_after_pause"] = snap(drv, ["camera_0"])["camera_0"]
        prev = None
        for _ in range(30):
            time.sleep(1)
            cur = snap(drv, PROCS)
            sig = json.dumps({p: (v["workers"], v["rs"]) for p, v in cur.items()}, sort_keys=True, default=str)
            if sig == prev:
                break
            prev = sig
        res["s2"] = cur
        res["rc_s2"] = _rc(drv)
    finally:
        h.stop()
    res["journal"] = journal(log_dir)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("stand47d: done", a.out, flush=True)


def _rc(drv):
    try:
        return drv.send_command("inspector", "get_stats", {}, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def pause_executor(drv, res, secs):
    st = _payload(drv.introspect_status("processor")) or {}
    names = [w for w in (st.get("workers") or {}) if "exec" in w.lower() or "pipeline" in w.lower()]
    res["pause_worker_names"] = list(st.get("workers") or {})
    if not names:
        res["pause_error"] = "executor worker not found"
        return False
    w = names[0]
    import psutil

    pid = st.get("pid")
    rss0 = psutil.Process(pid).memory_info().rss if pid else None
    t = time.perf_counter()
    res["pause_stop"] = drv.send_command("processor", "worker.stop", {"worker_name": w}, timeout=10)
    time.sleep(secs)
    res["pause_mid"] = snap(drv, ["processor"])
    rss1 = psutil.Process(pid).memory_info().rss if pid else None
    res["pause_start"] = drv.send_command("processor", "worker.start", {"worker_name": w}, timeout=10)
    t_res = time.perf_counter()
    # Дренаж: queue_wait_ms вернулся ниже 2 с или 30 с потолок.
    drain = None
    trace = []
    for _ in range(600):
        time.sleep(0.05)
        s = snap(drv, ["processor"])["processor"]["workers"].get(w, {})
        trace.append((round(time.perf_counter() - t_res, 3), s.get("queue_wait_ms")))
        if (s.get("queue_wait_ms") or 0) < 100:
            drain = round(time.perf_counter() - t_res, 3)
            break
    res["pause"] = {
        "worker": w,
        "stopped_s": round(t_res - t, 1),
        "rss0": rss0,
        "rss1": rss1,
        "drain_s": drain,
        "drain_trace": trace[:40],
        "after": snap(drv, PROCS),
    }
    return True


EV = re.compile(r"event inspection: (\S+): (.*?) trace=(\S+)")


def journal(log_dir: Path):
    rows = []
    # Только messages.log: observability.db — бинарный SQLite, текст в нём лежит повторно
    # (FTS, свободные страницы) и даёт ложные дубли (замер 2026-10-03: 95–462 на прогон).
    for f in log_dir.rglob("messages.log"):
        if not f.is_file():
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in EV.finditer(txt):
            rows.append((f.name, m.group(1), m.group(2)[:80], m.group(3)))
    by_file = {}
    for fn, *_ in rows:
        by_file[fn] = by_file.get(fn, 0) + 1
    # Одна строка может лежать в нескольких файлах (каналы scope BUSINESS) — считаем по самому полному.
    best = max(by_file, key=by_file.get) if by_file else None
    sel = [r for r in rows if r[0] == best]
    traces = [r[3] for r in sel]
    markers = [r for r in sel if "не проверен" in r[2]]
    dup = len(traces) - len(set(traces))
    return {
        "files": by_file,
        "file": best,
        "rows": len(sel),
        "distinct": len(set(traces)),
        "dup": dup,
        "markers": len(markers),
        "verdicts": len(sel) - len(markers),
        "actions": {k: sum(1 for r in sel if r[1].startswith(k)) for k in ("reject", "pass")},
        "marker_origins": {
            o: sum(1 for r in markers if f"({o}@" in r[2]) for o in ("lag", "stale_restore", "stale_exec", "door")
        },
        "sample": sel[:3],
    }


if __name__ == "__main__":
    main()
