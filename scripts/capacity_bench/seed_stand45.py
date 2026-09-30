"""ЗАТРАВКА для Task 4.8a (plans/transport-single-policy/task-4.8.md), НЕ готовый инструмент: Windows-only
(QueryProcessCycleTime + реестр ~MHz), без паспорта машины и самопроверки часов. Им сделан замер A/B Task 4.5
2026-09-30 (числа — plans/transport-single-policy/task-4.5.md, «Статус 4.5»).

Замер Task 4.5 (A/B): ядра процессов по тактам снаружи против state.cpu изнутри, fps, новые поля.

stand45.py <tag> <res: 1080|480> <fps> <secs> <port>
Запускать с cwd = стенд-worktree (его код и мерим), PYTHONPATH = cwd.
"""

import ctypes
import json
import re
import statistics
import sys
import tempfile
import time
import winreg
from ctypes import wintypes
from pathlib import Path

tag, res, fps, secs, port = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
S = Path(tempfile.gettempdir())
SRC = Path.cwd() / "multiprocess_prototype/backend/topology/inspection_full.yaml"  # 640x480, 25 fps
PROCS = ["camera_0", "processor", "renderer", "inspector", "storage", "gui"]
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wintypes.HANDLE
k32.QueryProcessCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]
with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
    HZ = float(winreg.QueryValueEx(k, "~MHz")[0]) * 1e6


def cycles(h):
    c = ctypes.c_ulonglong()
    k32.QueryProcessCycleTime(h, ctypes.byref(c))
    return c.value


def recipe():
    src = SRC.read_text(encoding="utf-8")
    if res == "1080":
        src = src.replace("resolution_width: 640", "resolution_width: 1920").replace(
            "resolution_height: 480", "resolution_height: 1080"
        )
    src = re.sub(r"source_target_fps: \d+", f"source_target_fps: {fps}", src)
    p = Path(tempfile.gettempdir()) / f"stand45_{res}_{fps}.yaml"
    p.write_text(src, encoding="utf-8")
    return str(p)


def dig(d, key):
    """Первое вхождение ключа в вложенном ответе драйвера."""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = dig(v, key)
            if r is not None:
                return r
    return None


def main():
    from backend_ctl.harness import BackendHarness, _find_payload

    h = BackendHarness(recipe=recipe(), port=port, ready_timeout=90, log_dir=str(S / f"logs45_{tag}"))
    drv = h.start()
    try:
        time.sleep(10)
        st = {p: drv.introspect_status(p) for p in PROCS}
        pids = {p: _find_payload(st[p], "pid", "process").get("pid") for p in PROCS}
        hs = {p: k32.OpenProcess(0x1000, False, pids[p]) for p in PROCS}
        c0 = {p: cycles(hs[p]) for p in PROCS}
        t0 = time.perf_counter()
        hz = {p: [] for p in PROCS}
        inner = {p: [] for p in PROCS}
        while time.perf_counter() - t0 < secs:
            ov = drv.system_overview(timeout=5)
            for p in PROCS:
                x = ov.get("processes", {}).get(p, {}).get("hz")
                if isinstance(x, (int, float)):
                    hz[p].append(float(x))
                cpu = dig(drv.introspect_status(p), "cpu")
                if isinstance(cpu, dict) and isinstance(cpu.get("cores"), (int, float)):
                    inner[p].append(float(cpu["cores"]))
            time.sleep(2)
        dt = time.perf_counter() - t0
        c1 = {p: cycles(hs[p]) for p in PROCS}
        out = {}
        for p in PROCS:
            ext = (c1[p] - c0[p]) / HZ / dt
            inn = statistics.mean(inner[p]) if inner[p] else None
            out[p] = {
                "ext_cores": round(ext, 3),
                "inner_cores_mean": round(inn, 3) if inn is not None else None,
                "err_pct": round((inn - ext) / ext * 100, 1) if inn is not None and ext > 0.02 else None,
                "hz_med": statistics.median(hz[p]) if hz[p] else None,
            }
        out["_total_ext_cores"] = round(sum(v["ext_cores"] for v in out.values()), 3)
        # Новые поля 4.5 (у A их нет — будет None)
        fields = {}
        for p in PROCS:
            tel = dig(drv.introspect_telemetry(p), "levels") or {}
            (S / f"s45_{tag}_{p}_levels.json").write_text(
                json.dumps(tel, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            fields[p] = {
                "cpu": dig(tel, "cpu"),
                "plugin_ms": dig(tel, "plugin_ms"),
                "queue_wait_ms": dig(tel, "queue_wait_ms"),
                "transport_ms": dig(tel, "transport_ms"),
                "pacer_late": dig(tel, "pacer_late"),
                "shm": {
                    k: v
                    for k, v in (dig(tel, "shm") or {}).items()
                    if k in ("bytes_written", "bytes_read", "bytes_mapped", "stale_drops", "torn_reads")
                },
            }
        out["_fields"] = fields
        (S / f"s45_{tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(tag, json.dumps({k: v for k, v in out.items() if k != "_fields"}, ensure_ascii=False), flush=True)
    finally:
        h.stop()


if __name__ == "__main__":
    main()
