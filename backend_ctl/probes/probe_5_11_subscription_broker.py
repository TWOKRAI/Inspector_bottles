# -*- coding: utf-8 -*-
"""Живой зонд Task 5.11 — брокер подписки переживает switch и ручной рестарт.

Закрывает последний открытый пункт приёмки 5.11:
    «живьём: switch + ручной рестарт на стенде, хвост не теряется (парой до/после)».

Стенд: headless BackendHarness, рецепт `dualcam_synth` + фундамент (`devices`
protected — он ПЕРЕЖИВЁТ switch), замена на `g1_perf_probe` через `topology.apply`
с `recipe_path`. Тот же стенд, что у R6 — пересозданные соседи + переживший.

Эмиттер записи — `health.report` с `level=ERROR`: диагностический впрыск, который
и задуман как детерминированная проверка канала наблюдаемости (tap на logger/error
менеджерах стоит с min_level=ERROR — ниже него хвост не форвардится).

Фазы (каждая — ПАРА, иначе не считается):
    P0  намерения НЕТ  → emit → записей быть не должно (ноль — это база сравнения)
    P1  ОДИН subscribe_all → emit → записи от ВСЕХ процессов
    P2  switch → emit → записи от пересозданных И от пережившего, БЕЗ переподписки
    P3  process.restart → emit → записи от свежей инкарнации
    P4  unsubscribe_all → restart → emit → снова ноль (намерение снято)

Запуск: ``python -m backend_ctl.probes.probe_5_11_subscription_broker``
(BACKEND_CTL выставляется самим зондом). Прогон ~3 минуты: поднимается реальный
headless-бэкенд, делается настоящий switch и настоящий рестарт.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE_A = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "dualcam_synth.yaml"
RECIPE_B = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "g1_perf_probe.yaml"

PROCS_A = ["devices", "camera_0", "camera_1", "consumer_0", "consumer_1"]
PROCS_B = ["devices", "synthetic_source", "consumer"]

PORT = 8791
FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    mark = "PASS" if ok else "FAIL"
    log(f"  [{mark}] {title}\n         {evidence}")
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
                {"message": f"{marker}::{name}", "level": "ERROR", "context": "probe_5_11"},
                timeout=8.0,
            )
        )
        sent[name] = bool(res.get("success"))
    return sent


def collect(drv, marker: str, wait: float = 6.0) -> dict:
    """Собрать записи с маркером, сгруппированные по процессу-источнику."""
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
    """Осушить курсор — чтобы записи прошлой фазы не считались в следующей."""
    for _ in range(3):
        drv.observability_records(level="DEBUG")
        time.sleep(0.2)


def main() -> int:
    harness = BackendHarness(recipe=RECIPE_A, with_base=True, port=PORT, ready_timeout=60.0)
    drv = harness.start()
    subscriber = drv._subscriber  # адрес драйвера (у него нет публичного геттера)
    log(f"\n=== стенд поднят: {RECIPE_A.name} + base, подписчик '{subscriber}' ===")

    try:
        alive = _leaf_result(drv.send_command("ProcessManager", "introspect.status", timeout=10.0))
        log(f"PM статус: success={alive.get('success')}")

        # ---------------- P0: намерения нет → тишина (база сравнения) ----------
        log("\n--- P0: намерение НЕ выдано ---")
        drain(drv)
        m0 = "PROBE5110"
        emit(drv, PROCS_A, m0)
        seen0 = collect(drv, m0, wait=5.0)
        check(not seen0, "без намерения хвост молчит", f"записей с маркером: {seen0 or '{}'}")

        # ---------------- P1: ОДИН вызов subscribe_all -------------------------
        log("\n--- P1: один вызов observability.tail.subscribe_all ---")
        sub = _leaf_result(
            drv.send_command(
                "ProcessManager",
                "observability.tail.subscribe_all",
                {"subscriber": subscriber},
                timeout=15.0,
            )
        )
        log(f"ответ брокера: {sub}")
        time.sleep(2.0)
        drain(drv)
        m1 = "PROBE5111"
        sent1 = emit(drv, PROCS_A, m1)
        seen1 = collect(drv, m1, wait=8.0)
        log(f"emit отправлен: {sent1}")
        missing1 = sorted(set(PROCS_A) - set(seen1))
        check(
            not missing1,
            "после ОДНОГО вызова хвост идёт со ВСЕХ процессов",
            f"пришли: {sorted(seen1)}; не пришли: {missing1 or 'нет'}",
        )

        # ---------------- P2: switch → хвост не потерян ------------------------
        log("\n--- P2: topology.apply (switch dualcam_synth → g1_perf_probe) ---")
        from multiprocess_prototype.backend.launch import load_topology_dict

        bp_b = load_topology_dict(RECIPE_B)
        applied = _leaf_result(
            drv.send_command(
                "ProcessManager",
                "topology.apply",
                {"topology_dict": bp_b, "recipe_path": str(RECIPE_B)},
                timeout=90.0,
            )
        )
        log(f"switch: success={applied.get('success')} ready={applied.get('ready')}")
        if not applied.get("success"):
            log(f"switch не удался целиком: {applied}")
        time.sleep(4.0)
        drain(drv)
        m2 = "PROBE5112"
        sent2 = emit(drv, PROCS_B, m2)
        seen2 = collect(drv, m2, wait=8.0)
        log(f"emit отправлен: {sent2}")
        missing2 = sorted(set(PROCS_B) - set(seen2))
        check(
            not missing2,
            "после switch хвост НЕ потерян (без единой переподписки)",
            f"пришли: {sorted(seen2)}; не пришли: {missing2 or 'нет'}",
        )
        check(
            "devices" in seen2,
            "переживший switch protected-процесс сохранил хвост",
            f"devices записей: {seen2.get('devices', 0)}",
        )

        # ---------------- P3: ручной рестарт -----------------------------------
        log("\n--- P3: ручной process.restart synthetic_source ---")
        before_pid = _leaf_result(drv.send_command("synthetic_source", "introspect.status", timeout=10.0)).get("pid")
        restarted = drv.system_command({"cmd": "process.restart", "process_name": "synthetic_source"}, timeout=60.0)
        log(f"restart: {_leaf_result(restarted)}")
        time.sleep(5.0)
        after_pid = _leaf_result(drv.send_command("synthetic_source", "introspect.status", timeout=15.0)).get("pid")
        log(f"pid: до={before_pid} после={after_pid}")
        drain(drv)
        m3 = "PROBE5113"
        sent3 = emit(drv, ["synthetic_source"], m3)
        seen3 = collect(drv, m3, wait=8.0)
        log(f"emit отправлен: {sent3}")
        check(
            "synthetic_source" in seen3,
            "после ручного рестарта хвост НЕ потерян",
            f"записей от свежей инкарнации: {seen3.get('synthetic_source', 0)} (pid {before_pid}→{after_pid})",
        )

        # ---------------- P4: пара — намерение снято → тишина ------------------
        log("\n--- P4: unsubscribe_all → рестарт → тишина ---")
        unsub = _leaf_result(
            drv.send_command(
                "ProcessManager",
                "observability.tail.unsubscribe_all",
                {"subscriber": subscriber},
                timeout=15.0,
            )
        )
        log(f"ответ брокера: {unsub}")
        drv.system_command({"cmd": "process.restart", "process_name": "synthetic_source"}, timeout=60.0)
        time.sleep(5.0)
        drain(drv)
        m4 = "PROBE5114"
        emit(drv, PROCS_B, m4)
        seen4 = collect(drv, m4, wait=6.0)
        check(
            not seen4,
            "намерение снято → пересозданный процесс молчит",
            f"записей с маркером: {seen4 or '{}'}",
        )

        # ---------------- readback брокера -------------------------------------
        snap = _leaf_result(drv.send_command("ProcessManager", "introspect.observability", timeout=15.0))
        broker = snap.get("broker") if isinstance(snap, dict) else None
        log(f"\nreadback брокера после отписки: {broker}")

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
