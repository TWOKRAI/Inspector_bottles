# -*- coding: utf-8 -*-
"""Живая приёмка Task 2.1 — то, что в pytest недоказуемо по построению.

Четыре критерия закрываются только настоящим процессом, потому что в стенде
тестов нет ни `StatsManager`, ни слота `observation`: прогон там прямо печатает
«метрика писать некуда», то есть доказано лишь, что плагин зовёт правильные
дороги правильными именами, а не что числа доезжают.

| критерий | чем закрывается здесь |
|---|---|
| счётчики видны в `introspect.telemetry` -> `levels` | опрос уровней у живого процесса |
| `history_query(metric="otel_export.received")` | чтение стора наблюдаемости |
| Н-6: `threading.get_ident()` в хендлере | `handler_threads` в `otel_export.status` |
| перенос Task 0.5: `endpoint` из ФРАГМЕНТА, не `""` | `introspect.registers` |

**Порядок запуска (стенд 8765 эксклюзивен — занять, объявить, освободить):**

    # окно 1: бэкенд
    BACKEND_CTL=1 python multiprocess_prototype/run.py \\
        multiprocess_prototype/backend/topology/otel_export.yaml

    # окно 2: эта проба
    python -m tools.otel_stand.task21_proof

Проба НИЧЕГО не чинит и ничего не пишет в дерево — только спрашивает и печатает
числа. Вердикт по каждому критерию отдельный: «не доказано» и «опровергнуто» —
разные исходы, и сводить их к одному FAIL значило бы прятать, чего мы не знаем.
"""

from __future__ import annotations

import sys
import time
from typing import Any

PROCESS = "otel_export"
#: Даём хвосту натечь: камера-симулятор на 10 fps, брокер разворачивает намерение
#: на шве старта, история пишется фоновой пачкой с тактом дренажа ~100 мс.
_SETTLE_SEC = 20.0

#: Восемь имён словаря счётчиков БЕЗ точки — так они лежат в плоскости уровней
#: (`state.plugins.otel_export.<имя>`). Точечные имена законны только в stats.
COUNTER_NAMES = (
    "received",
    "exported",
    "skipped_numbers",
    "mapper_rejected",
    "attr_coerced",
    "dropped_overflow",
    "export_failed",
    "resource_evicted",
)


def _verdict(name: str, ok: bool | None, detail: str) -> tuple[str, bool | None]:
    mark = {True: "ДОКАЗАНО   ", False: "ОПРОВЕРГНУТО", None: "НЕ ДОКАЗАНО"}[ok]
    print(f"[{mark}] {name}\n              {detail}")
    return name, ok


def main() -> int:
    from backend_ctl.driver import BackendDriver

    results: list[tuple[str, bool | None]] = []

    with BackendDriver(port=8765) as drv:
        print(f"[proof] подключился к стенду; даю системе {_SETTLE_SEC} с натечь хвостом...")
        time.sleep(_SETTLE_SEC)

        # ------------------------------------------------------------------ #
        # 1. Состояние плагина и детектор потоков (Н-6, Р-11, Р-13)
        # ------------------------------------------------------------------ #
        status: dict[str, Any] = drv.send_command(PROCESS, "otel_export.status") or {}
        # Ответ PM приезжает конвертом; полезное лежит в result/data по дороге.
        payload = status.get("result", status.get("data", status))
        if not isinstance(payload, dict):
            payload = status
        print(f"\n[proof] otel_export.status -> {payload!r}\n")

        state = payload.get("state")
        results.append(
            _verdict(
                "Р-13/Р-14: состояние плагина читается командой",
                state in ("ready", "degraded", "error") if state is not None else None,
                f"state={state!r}, reason={payload.get('reason')!r}, sdk={payload.get('sdk')!r}",
            )
        )

        threads = payload.get("handler_threads")
        if not isinstance(threads, list):
            ok_threads: bool | None = None
            detail = f"ключа handler_threads в ответе нет: {payload.keys()}"
        elif len(threads) == 0:
            # Ноль — НЕ доказательство однопоточности: это «хендлер не звали ни
            # разу». Пятое прочтение нуля: пустая ось, а не свойство.
            ok_threads = None
            detail = "список пуст — хендлер не вызывался ни разу, об однопоточности это не говорит НИЧЕГО"
        else:
            ok_threads = len(threads) == 1
            detail = f"идентификаторов потоков: {len(threads)} -> {threads}"
        results.append(_verdict("Н-6: хендлер исполняется в ОДНОМ потоке", ok_threads, detail))

        counters = payload.get("counters") or {}
        received_cmd = counters.get("received")
        results.append(
            _verdict(
                "приём вообще состоялся (записи дошли до хендлера)",
                bool(received_cmd) if received_cmd is not None else None,
                f"счётчики из команды: {counters!r}",
            )
        )

        # ------------------------------------------------------------------ #
        # 2. Плоскость уровней — introspect.telemetry -> levels
        # ------------------------------------------------------------------ #
        telemetry = drv.introspect_telemetry(PROCESS) or {}
        tp = telemetry.get("result", telemetry.get("data", telemetry))
        levels = (tp or {}).get("levels") if isinstance(tp, dict) else None
        if levels is None:
            ok_levels: bool | None = None
            detail = "levels=None — сенсоров нет (нет heartbeat/показаний), это не отказ команды"
        else:
            flat = {k.split(".")[-1] for k in levels} if isinstance(levels, dict) else set()
            seen = sorted(set(COUNTER_NAMES) & flat)
            ok_levels = len(seen) > 0
            detail = f"нашлось {len(seen)} из 8 имён словаря: {seen}; всего листьев в levels: {len(levels)}"
        results.append(_verdict("Р-7: счётчики видны в introspect.telemetry -> levels", ok_levels, detail))

        # ------------------------------------------------------------------ #
        # 3. Плоскость чисел — history_query по точечному имени
        # ------------------------------------------------------------------ #
        history = drv.history_query(metric="otel_export.received", limit=20) or {}
        hp = history.get("result", history.get("data", history))
        rows = (hp or {}).get("rows") if isinstance(hp, dict) else None
        if rows is None:
            ok_hist: bool | None = None
            detail = f"ключа rows в ответе нет: {hp!r}"
        else:
            ok_hist = len(rows) > 0
            detail = f"строк по metric='otel_export.received': {len(rows)}"
            if rows:
                detail += f"; первая: {rows[0]!r}"
        results.append(_verdict("Р-7: счётчики видны в history_query (плоскость чисел)", ok_hist, detail))

        # ------------------------------------------------------------------ #
        # 4. Перенос Task 0.5 — endpoint приехал из фрагмента, а не дефолтом ""
        # ------------------------------------------------------------------ #
        regs = drv.introspect_registers(PROCESS) or {}
        rp = regs.get("result", regs.get("data", regs))
        text = repr(rp)
        endpoint_effective = payload.get("endpoint")
        ok_reg = None
        if "127.0.0.1:4318" in text:
            ok_reg = True
            detail = "в ответе introspect.registers виден endpoint из фрагмента"
        elif "endpoint" in text:
            ok_reg = False
            detail = f"регистр есть, но endpoint не из фрагмента; ответ: {text[:400]}"
        else:
            detail = f"регистра otel_export в ответе не видно вовсе: {text[:400]}"
        detail += f" | endpoint в otel_export.status: {endpoint_effective!r}"
        results.append(_verdict("Task 0.5: endpoint из ФРАГМЕНТА, не пустой дефолт", ok_reg, detail))

    # ---------------------------------------------------------------------- #
    print("\n=== СВОДКА ===")
    proved = sum(1 for _n, ok in results if ok is True)
    refuted = sum(1 for _n, ok in results if ok is False)
    unknown = sum(1 for _n, ok in results if ok is None)
    for name, ok in results:
        label = "ДОКАЗАНО" if ok is True else ("ОПРОВЕРГНУТО" if ok is False else "НЕ ДОКАЗАНО")
        print(f"  {label:<13}{name}")
    print(f"\nдоказано {proved}, опровергнуто {refuted}, не доказано {unknown}")
    # Ненулевой код только на ОПРОВЕРГНУТО: «не доказано» — это про пробу, а не
    # про предмет, и молча превращать одно в другое нельзя.
    return 1 if refuted else 0


if __name__ == "__main__":
    sys.exit(main())
