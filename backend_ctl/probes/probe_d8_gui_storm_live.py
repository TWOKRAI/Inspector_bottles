# -*- coding: utf-8 -*-
"""Живая приёмка D8 — headless-презентация принимает данные, отказов доставки нет.

Зачем живьём. Свойство наблюдаемо только на поднятой системе: счётчики роутера
живут в процессе-отправителе, а «кому не доставили» видно лишь по его же
``targets``. Тест на дублях показал бы отказ очереди, но не то, что адресат
называется ``gui`` и что его в топологии стенда нет.

**База ДО правки** (тот же стенд ``webcam_sketch``, то же окно 30 с)::

    процессы: ProcessManager, camera_0, devices, lines, points, pult, seg  (gui НЕТ)
    ProcessManager: sent_attempted +1439, sent_ok +21, errors_delivery_failed +1418
    журнал: send [delivery_failed] ни один из 1 адресатов не принял:
            channel=None command=None type='data' targets=['gui']
    у продюсеров (camera_0/seg/points/lines): errors_delivery_failed +0

Последнее — суть диагноза: у продюсера имени ``gui`` нет ни очередью, ни каналом,
поэтому билет уходит хабу relay'ем и считается доставленным, а провал случается
уже на хабе. Копилось не там, где отправляли.

Проверки приёмки:

    P1  Процесс ``gui`` есть в топологии стенда и отвечает на introspect.
    P2  ``errors_delivery_failed`` за окно = 0 у ВСЕХ процессов (пара к базе).
    P3  ``gui.received`` за окно РАСТЁТ — приёмник дренирует, а не просто
        существует с полной очередью (иначе P2 держался бы вытеснением).
    P4  ``introspect.*`` отвечает на всех процессах, включая boot-окно.

Запуск: ``python -m backend_ctl.probes.probe_d8_gui_storm_live [секунды]``
Стенд одиночный — порт 8765 не терпит двух.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "webcam_sketch.yaml"

#: Ключи роутера, различающие классы отказа отправки (Ф6.7) + приём.
KEYS = ("sent_attempted", "sent_ok", "received", "errors_delivery_failed", "errors_no_route", "errors")

FAILURES: list = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def router_stats(drv, process: str) -> Dict[str, int]:
    """Снимок счётчиков роутера процесса; пустой dict — процесс не ответил."""
    try:
        payload = _leaf_result(drv.send_command(process, "introspect.router_stats", {}, timeout=20.0)) or {}
    except Exception as exc:  # noqa: BLE001 — молчащий процесс не должен ронять пробу
        log(f"    [!] {process}: introspect.router_stats не ответил: {exc!r}")
        return {}
    # Ключ ответа — `router_stats` (`_cmd_introspect_router_stats`). Первая редакция
    # пробы читала `router` и получала нули на процессе, чей журнал в тот же момент
    # писал `errors_delivery_failed=1354`: неверный ключ читается как «отказов нет».
    # Поэтому ниже — не `.get(...) or {}`, а явный отказ, если секции нет.
    router = payload.get("router_stats") if isinstance(payload, dict) else None
    if not isinstance(router, dict):
        keys = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        log(f"    [!] {process}: в ответе нет секции 'router_stats'; ключи={keys}")
        return {}
    return {key: int(router.get(key, 0) or 0) for key in KEYS}


def _process_names(overview: dict) -> list:
    """Имена процессов из ответа system_overview (форма ответа сверяется здесь же)."""
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
    log(f"  [!] system_overview: неожиданная форма processes={type(procs).__name__}; ключи={sorted(overview)}")
    return []


def main() -> int:
    window = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0

    log("=" * 78)
    log(f"D8 — живая приёмка headless-презентации, окно {window:.0f} с")
    log("=" * 78)

    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    drv = harness.start()
    try:
        overview = drv.system_overview(timeout=25.0) or {}
        processes = sorted(_process_names(overview))

        log("\n--- P1: процесс презентации есть в топологии ---")
        check("gui" in processes, "'gui' объявлен и поднят", f"процессы стенда ({len(processes)}): {processes}")

        log("\n--- снимок счётчиков (начало окна; boot-окно уже позади) ---")
        before = {name: router_stats(drv, name) for name in processes}
        for name, snap in before.items():
            if snap:
                log(f"  {name}: {snap}")
        boot_silent = [name for name in processes if not before.get(name)]
        check(
            not boot_silent,
            "introspect отвечает у всех процессов в начале окна",
            f"не ответили: {boot_silent or 'нет'}",
        )

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

        log("\n--- P2: отказов доставки нет ни у кого ---")
        storm = {n: d["errors_delivery_failed"] for n, d in deltas.items() if d["errors_delivery_failed"]}
        check(
            not storm,
            "errors_delivery_failed за окно = 0 у всех",
            f"ненулевые: {storm or 'нет'} (база до правки: ProcessManager +1418 за 30.0 с)",
        )
        no_route = {n: d["errors_no_route"] for n, d in deltas.items() if d["errors_no_route"]}
        check(
            not no_route,
            "errors_no_route за окно = 0 у всех (адрес не стал «ненайденным»)",
            f"ненулевые: {no_route or 'нет'}",
        )

        log("\n--- P3: презентация ДРЕНИРУЕТ, а не молчит с полной очередью ---")
        gui_delta = deltas.get("gui") or {}
        received = gui_delta.get("received", 0)
        check(
            received > 0,
            "gui.received за окно > 0",
            f"received +{received} за {elapsed:.1f} с (={received / elapsed:.1f}/с)",
        )

        log("\n--- P4: introspect отвечает в конце окна ---")
        silent = [name for name in processes if not (after.get(name) or {})]
        check(not silent, "все процессы ответили", f"не ответили: {silent or 'нет'}")
    finally:
        harness.stop()

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
