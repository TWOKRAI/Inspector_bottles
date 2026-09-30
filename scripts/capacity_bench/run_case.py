"""Один кейс стенда: поднять систему, прогреть, померить CPU процессов снаружи, снять поля.

Запуск (cwd и PYTHONPATH = МЕРЯЕМОЕ дерево — его `backend_ctl` и код мерим):

    python <bench>/run_case.py --recipe R.yaml --secs 30 --port 8775 --out case.json

Только stdlib + psutil + yaml: скрипт запускают против чужого дерева (baseline-worktree), где
пакета `scripts.capacity_bench` может не быть, поэтому соседи импортируются по пути файла.
Стенд поднимается ЗДЕСЬ — замок стенда держит вызывающий (лид), не инструмент.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

import yaml

if __package__:  # импорт как часть пакета (тесты): без правки sys.path
    from . import cpu_probe, fields
else:  # запуск как скрипта: соседи по пути файла, `scripts.*` может не быть
    sys.path.insert(0, str(Path(__file__).parent))
    import cpu_probe  # noqa: E402
    import fields  # noqa: E402

WARMUP_S = 10
POLL_S = 2


def _dig(d, key):
    """Первое вхождение ключа во вложенном ответе драйвера."""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            r = _dig(v, key)
            if r is not None:
                return r
    return None


def _recipe_processes(recipe_path: str) -> list[str]:
    recipe = yaml.safe_load(Path(recipe_path).read_text(encoding="utf-8"))
    procs = recipe.get("processes") or []
    return [p["process_name"] for p in procs if isinstance(p, dict) and "process_name" in p]


def _pids(drv, names: list[str], find_payload) -> dict[str, int]:
    """pid только тех процессов рецепта, что ответили на introspect_status."""
    pids = {}
    for name in names:
        try:
            pid = find_payload(drv.introspect_status(name), "pid", "process").get("pid")
        except Exception as exc:  # noqa: BLE001 — процесс не ответил: не меряем, но и не роняем кейс
            print(f"run_case: {name} not measured: {type(exc).__name__}", file=sys.stderr)
            continue
        if isinstance(pid, int):
            pids[name] = pid
    return pids


def _fields(drv, name: str) -> dict:
    return fields.extract_fields(_dig(drv.introspect_telemetry(name), "levels") or {})


def run(recipe: str, secs: float, port: int) -> dict:
    from backend_ctl.harness import BackendHarness, _find_payload

    names = _recipe_processes(recipe)
    probes: dict[str, cpu_probe.ProcessCpu] = {}
    with tempfile.TemporaryDirectory(prefix="bench_logs_", ignore_cleanup_errors=True) as log_dir:
        h = BackendHarness(recipe=recipe, port=port, ready_timeout=90, log_dir=log_dir)
        drv = h.start()
        try:
            time.sleep(WARMUP_S)
            pids = _pids(drv, names, _find_payload)
            probes = {name: cpu_probe.ProcessCpu(pid) for name, pid in pids.items()}
            c0 = {name: p.read_seconds() for name, p in probes.items()}
            # Снимок счётчиков в тот же момент, что и c0: shm/pacer_late копятся с запуска процесса.
            before = {name: _fields(drv, name) for name in probes}
            t0 = time.perf_counter()
            hz_polled: dict[str, list[float]] = {name: [] for name in probes}
            while time.perf_counter() - t0 < secs:
                overview = drv.system_overview(timeout=5)
                for name in probes:
                    hz = overview.get("processes", {}).get(name, {}).get("hz")
                    if isinstance(hz, (int, float)):
                        hz_polled[name].append(float(hz))
                time.sleep(POLL_S)
            dt = time.perf_counter() - t0
            c1 = {name: p.read_seconds() for name, p in probes.items()}

            processes = {}
            for name in probes:
                got = fields.window(before[name], _fields(drv, name))
                if hz_polled[name]:  # медиана опросов за окно, а не один снимок в конце
                    got["hz"] = statistics.median(hz_polled[name])
                processes[name] = {"ext_cores": round((c1[name] - c0[name]) / dt, 3), **got}
            return {
                "processes": processes,
                "total_ext_cores": round(sum(p["ext_cores"] for p in processes.values()), 3),
                "missing": [n for n in names if n not in probes],
            }
        finally:
            for p in probes.values():
                p.close()
            h.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--secs", type=float, required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = run(args.recipe, args.secs, args.port)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("run_case: total_ext_cores", result["total_ext_cores"], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
