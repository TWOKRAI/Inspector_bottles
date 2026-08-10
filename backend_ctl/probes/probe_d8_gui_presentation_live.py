# -*- coding: utf-8 -*-
"""Живая проверка ВТОРОЙ половины пары D8 — режим с презентацией не деградировал.

Пара, а не один случай. Первая половина (`probe_d8_gui_storm_live`) судит headless:
процесс `gui` в дренирующем воплощении, отказов доставки нет. Эта — режим с окном:
тот же процесс под Qt-классом, кадры доезжают, отказов по-прежнему нет.

Почему отдельной пробой, а не флагом первой. Первая ПОДНИМАЕТ стенд сама
(`BackendHarness`), а окно так поднять нельзя: Qt-петля живёт в главном потоке
своего процесса. Здесь проба ПОДКЛЮЧАЕТСЯ к уже запущенному бэкенду
(`multiprocess_prototype/frontend/run.py`), то есть судит ровно то, что видит
оператор, а не свою же сборку.

Проверки:

    G1  Процесс `gui` есть и отвечает на introspect.
    G2  Кадры доезжают до презентации: `gui.received` растёт за окно.
    G3  `errors_no_route` = 0 — адрес `gui` резолвится (это и есть свойство D8).
    G4  Продюсеры живы: `sent_ok` растёт (иначе «нет отказов» держалось бы тем,
        что никто ничего не шлёт).

**Почему G3 про `no_route`, а не про `delivery_failed`.** Первая редакция пробы
требовала `errors_delivery_failed == 0` и была красной: живой GUI отстаёт от трёх
продюсеров, его data-очередь переполняется, и `send_to_queue` отвечает отказом —
`lines` 22, `points` 22, `seg` 21 за 60 с (0.36/с против 47/с шторма). Роутер
считает ОБА случая одним ключом: «приёмника нет» и «приёмник не успевает». D8
чинит первый, второй — свойство живого GUI и к этой задаче отношения не имеет.

Что это НЕ регресс — доказано не рассуждением: сборка режима с презентацией
побитово идентична состоянию до правки (сверены `proc_dict` всех 7 процессов,
0 расхождений после нормализации корня пути). Отсюда и форма проверки: класс
«адреса нет» ловится парой `errors_no_route == 0` + растущий `gui.received`,
а число отказов-от-переполнения печатается как факт, а не судится порогом,
взятым с потолка.

Запуск (бэкенд с окном уже поднят отдельно, BACKEND_CTL=1)::

    python -m backend_ctl.probes.probe_d8_gui_presentation_live [секунды]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("BACKEND_CTL", "1")

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import BackendDriver, _leaf_result  # noqa: E402

KEYS = ("sent_attempted", "sent_ok", "received", "errors_delivery_failed", "errors_no_route", "errors")

FAILURES: list = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def router_stats(drv: BackendDriver, process: str) -> Dict[str, int]:
    try:
        payload = _leaf_result(drv.send_command(process, "introspect.router_stats", {}, timeout=20.0)) or {}
    except Exception as exc:  # noqa: BLE001
        log(f"    [!] {process}: introspect.router_stats не ответил: {exc!r}")
        return {}
    router = payload.get("router_stats") if isinstance(payload, dict) else None
    if not isinstance(router, dict):
        return {}
    return {key: int(router.get(key, 0) or 0) for key in KEYS}


def _process_names(overview: dict) -> list:
    procs = overview.get("processes")
    if isinstance(procs, dict):
        return [str(k) for k in procs]
    if isinstance(procs, list):
        names = []
        for item in procs:
            if isinstance(item, dict):
                name = item.get("process") or item.get("name") or item.get("process_name")
                if name:
                    names.append(str(name))
            elif item:
                names.append(str(item))
        return names
    return []


def main() -> int:
    window = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0

    log("=" * 78)
    log(f"D8 — живая проверка режима С ПРЕЗЕНТАЦИЕЙ, окно {window:.0f} с")
    log("=" * 78)

    drv = BackendDriver()
    drv.connect()
    try:
        overview = drv.system_overview(timeout=25.0) or {}
        processes = sorted(_process_names(overview))

        log("\n--- G1: процесс презентации живёт и отвечает ---")
        check("gui" in processes, "'gui' поднят", f"процессы ({len(processes)}): {processes}")

        before = {name: router_stats(drv, name) for name in processes}
        for name, snap in before.items():
            if snap:
                log(f"  {name}: {snap}")

        started = time.monotonic()
        time.sleep(window)
        elapsed = time.monotonic() - started

        log("\n--- дельта за окно ---")
        after = {name: router_stats(drv, name) for name in processes}
        deltas: Dict[str, Dict[str, int]] = {}
        for name in processes:
            b, a = before.get(name) or {}, after.get(name) or {}
            if not b or not a:
                continue
            deltas[name] = {key: a[key] - b[key] for key in KEYS}
            log(f"  {name}: {deltas[name]}")

        log("\n--- G2: кадры доезжают до презентации ---")
        gui_received = (deltas.get("gui") or {}).get("received", 0)
        check(
            gui_received > 0,
            "gui.received за окно > 0",
            f"received +{gui_received} за {elapsed:.1f} с (={gui_received / elapsed:.1f}/с)",
        )

        log("\n--- G3: адрес презентации резолвится ---")
        no_route = {n: d["errors_no_route"] for n, d in deltas.items() if d["errors_no_route"]}
        check(
            not no_route,
            "errors_no_route = 0 у всех (адресат найден)",
            f"ненулевые: {no_route or 'нет'}",
        )
        # Отказы переполнения печатаются числом, но НЕ судятся: это backpressure
        # живого GUI (см. докстринг), а не класс дефекта D8. Порог с потолка здесь
        # был бы вреднее молчания — он бы краснел от загрузки машины.
        overflow = {n: d["errors_delivery_failed"] for n, d in deltas.items() if d["errors_delivery_failed"]}
        total = sum(overflow.values())
        log(
            f"  [ФАКТ] отказы доставки от переполнения очереди GUI: {overflow or 'нет'}; "
            f"всего {total} за {elapsed:.0f} с (={total / elapsed:.2f}/с). "
            f"Для сравнения headless-шторм ДО D8: 47/с при отсутствующем приёмнике."
        )

        log("\n--- G4: продюсеры живы (иначе «нет отказов» ничего не значит) ---")
        producers = {n: d["sent_ok"] for n, d in deltas.items() if n not in ("gui", "ProcessManager")}
        alive = {n: v for n, v in producers.items() if v > 0}
        check(
            len(alive) >= 2,
            "хотя бы два продюсера реально отправляли",
            f"sent_ok за окно: {producers}",
        )
    finally:
        drv.close()

    log("\n" + "=" * 78)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for item in FAILURES:
            log(f"  - {item}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
