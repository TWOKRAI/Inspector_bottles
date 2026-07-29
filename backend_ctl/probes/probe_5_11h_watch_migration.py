# -*- coding: utf-8 -*-
"""Живой зонд Task 5.11.h — watch_like_gui через брокер переживает switch и рестарт.

Приёмка миграции драйвера: контур автоподписки снесён, хвост держится ОДНИМ
намерением у брокера PM. Юнит-тесты доказывают форму вызовов; здесь доказывается
то, чего они по построению не видят — что после реального switch и реального
рестарта записи от ПЕРЕСОЗДАННЫХ процессов продолжают приходить, хотя драйвер не
сделал ни одной переподписки.

Именно этот сценарий прежний контур и не покрывал: его триггером было
supervisor-событие ``recovered``, которого нет ни на switch, ни на ручном рестарте.

Фазы (каждая — ПАРА, иначе не считается):
    P0  watch НЕ включён            → emit → тишина (база сравнения)
    P1  watch_like_gui()            → emit → записи от ВСЕХ процессов
    P2  switch рецепта              → emit → записи от пересозданных И пережившего
    P3  ручной process.restart      → emit → записи от свежей инкарнации
    P4  unwatch()                   → emit → снова тишина
    P5  контур не воскрес           → нет потоков backend-ctl-resub

Запуск: ``python -m backend_ctl.probes.probe_5_11h_watch_migration`` (~3 мин).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE_A = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "dualcam_synth.yaml"
RECIPE_B = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "g1_perf_probe.yaml"

PROCS_A = ["devices", "camera_0", "camera_1", "consumer_0", "consumer_1"]
PROCS_B = ["devices", "synthetic_source", "consumer"]

PORT = 8792
FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def emit(drv, procs: list[str], marker: str) -> dict:
    """Впрыснуть в каждый процесс детерминированную ERROR-запись с маркером."""
    sent = {}
    for name in procs:
        res = _leaf_result(
            drv.send_command(
                name,
                "health.report",
                {"message": f"{marker}::{name}", "level": "ERROR", "context": "probe_5_11h"},
                timeout=8.0,
            )
        )
        sent[name] = bool(res.get("success"))
    return sent


def collect(drv, marker: str, wait: float = 8.0) -> dict:
    seen: dict[str, int] = {}
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        for rec in drv.observability_records(level="DEBUG"):
            if marker in str(rec.get("message") or ""):
                key = str(rec.get("process") or "?")
                seen[key] = seen.get(key, 0) + 1
        time.sleep(0.3)
    return seen


def drain(drv) -> None:
    for _ in range(3):
        drv.observability_records(level="DEBUG")
        time.sleep(0.2)


def main() -> int:
    harness = BackendHarness(recipe=RECIPE_A, with_base=True, port=PORT, ready_timeout=60.0)
    drv = harness.start()
    log(f"\n=== стенд поднят: {RECIPE_A.name} + base ===")

    try:
        # ---------------- P0: watch не включён → тишина -------------------------
        log("\n--- P0: watch НЕ включён ---")
        drain(drv)
        emit(drv, PROCS_A, "H5110")
        seen0 = collect(drv, "H5110", wait=5.0)
        check(not seen0, "без watch хвост молчит", f"записей: {seen0 or '{}'}")

        # ---------------- P1: watch_like_gui одним вызовом ----------------------
        log("\n--- P1: watch_like_gui() ---")
        summary = drv.watch_like_gui()
        obs = summary.get("observability") or {}
        log(f"ответ брокера: {obs}")
        check(
            summary.get("success") is True and obs.get("success") is not False,
            "watch_like_gui поднял профиль одним намерением",
            f"success={summary.get('success')}, брокер={obs.get('success')}",
        )
        time.sleep(2.0)
        drain(drv)
        emit(drv, PROCS_A, "H5111")
        seen1 = collect(drv, "H5111")
        missing1 = sorted(set(PROCS_A) - set(seen1))
        check(not missing1, "хвост идёт со ВСЕХ процессов", f"пришли: {sorted(seen1)}; нет: {missing1 or 'нет'}")

        # ---------------- P2: switch -------------------------------------------
        log("\n--- P2: switch рецепта ---")
        from multiprocess_prototype.backend.launch import load_topology_dict

        applied = _leaf_result(
            drv.send_command(
                "ProcessManager",
                "topology.apply",
                {"topology_dict": load_topology_dict(RECIPE_B), "recipe_path": str(RECIPE_B)},
                timeout=90.0,
            )
        )
        log(f"switch: success={applied.get('success')}")
        time.sleep(4.0)
        drain(drv)
        emit(drv, PROCS_B, "H5112")
        seen2 = collect(drv, "H5112")
        missing2 = sorted(set(PROCS_B) - set(seen2))
        check(
            not missing2,
            "после switch хвост НЕ потерян (драйвер не переподписывался)",
            f"пришли: {sorted(seen2)}; нет: {missing2 or 'нет'}",
        )

        # ---------------- P3: ручной рестарт ------------------------------------
        log("\n--- P3: ручной process.restart ---")
        before = _leaf_result(drv.send_command("synthetic_source", "introspect.status", timeout=10.0)).get("pid")
        drv.system_command({"cmd": "process.restart", "process_name": "synthetic_source"}, timeout=60.0)
        time.sleep(5.0)
        after = _leaf_result(drv.send_command("synthetic_source", "introspect.status", timeout=15.0)).get("pid")
        drain(drv)
        emit(drv, ["synthetic_source"], "H5113")
        seen3 = collect(drv, "H5113")
        check(
            "synthetic_source" in seen3,
            "после ручного рестарта хвост НЕ потерян",
            f"записей: {seen3.get('synthetic_source', 0)} (pid {before}→{after}) "
            f"— прежний триггер 'recovered' этот путь не покрывал",
        )

        # ---------------- P4: unwatch → тишина ----------------------------------
        log("\n--- P4: unwatch() ---")
        un = drv.unwatch()
        log(f"unwatch: {un.get('observability')}")
        time.sleep(2.0)
        drain(drv)
        emit(drv, PROCS_B, "H5114")
        seen4 = collect(drv, "H5114", wait=6.0)
        check(not seen4, "после unwatch хвост молчит", f"записей: {seen4 or '{}'}")

        # ---------------- P5: контур не воскрес ---------------------------------
        threads = [t.name for t in threading.enumerate() if t.name == "backend-ctl-resub"]
        check(not threads, "контур автоподписки не воскрес", f"потоки backend-ctl-resub: {threads or 'нет'}")

    finally:
        harness.stop()

    log("\n" + "=" * 70)
    if FAILURES:
        log(f"ИТОГ: {len(FAILURES)} провал(ов)")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("ИТОГ: все проверки зелёные")
    return 0


if __name__ == "__main__":
    sys.exit(main())
