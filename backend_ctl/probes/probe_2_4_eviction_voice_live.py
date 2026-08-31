# -*- coding: utf-8 -*-
"""Живая приёмка Task 2.4: вытеснение колец звучит — один раз на эпизод.

Зонд НИЧЕГО не поднимает: подключается своим экземпляром ``BackendDriver`` к уже
работающей системе. Это важно именно здесь — MCP-драйвер сессии живёт со своим
(возможно, старым) кодом, а проверять надо ТОТ код, что лежит в рабочем дереве.

Проверки (числа, не прилагательные):

    L1  под ``watch_like_gui`` за 30 с без чтения вытеснение ЕСТЬ: ``evicted > 0``
        хотя бы у одного кольца (иначе судить нечего — прогон объявляется негодным,
        а не «успешным без голосов»);
    L2  голос прозвучал и НЕСЁТ ЧИСЛО: хотя бы одна WARNING-запись логгера
        ``backend_ctl.events``, и в её тексте есть имя кольца и цифры;
    L3  голос — ОДИН на эпизод, а не на запись: голосов кратно меньше вытеснений
        (при непрерывном бурсте ожидается ровно 1 на кольцо, поэтому потолок —
        число колец, а не число вытеснений);
    L4  контроль-отрицание: до подписки, на тихом кольце, голосов НЕТ.

Запуск (система должна работать с BACKEND_CTL=1)::

    .venv/Scripts/python.exe -m backend_ctl.probes.probe_2_4_eviction_voice_live
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import BackendDriver  # noqa: E402

WATCH_SECONDS = 30.0

_failures: List[str] = []


def log(text: str) -> None:
    print(text, flush=True)


def check(ok: bool, name: str, detail: str) -> None:
    log(f"  [{'OK  ' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        _failures.append(name)


class _VoiceCollector(logging.Handler):
    """Ловит ИМЕННО голоса hub'а: логгер backend_ctl.events, уровень WARNING."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "backend_ctl.events" and record.levelno >= logging.WARNING:
            self.records.append(record.getMessage())


def main() -> int:
    collector = _VoiceCollector()
    hub_logger = logging.getLogger("backend_ctl.events")
    hub_logger.addHandler(collector)
    hub_logger.setLevel(logging.WARNING)

    drv = BackendDriver()
    drv.connect()
    try:
        log("--- L4: контроль-отрицание (до подписки поток пуст) ---")
        time.sleep(2.0)
        check(len(collector.records) == 0, "L4 тихое кольцо молчит", f"голосов {len(collector.records)} (ожидание 0)")

        log(f"\n--- L1/L2/L3: watch_like_gui, {WATCH_SECONDS:.0f} с без чтения ---")
        before = len(collector.records)
        drv.watch_like_gui()
        time.sleep(WATCH_SECONDS)

        stats: Dict[str, Any] = drv.events_stats()
        planes = stats["planes"]
        evicted_by_ring = {p: planes[p]["evicted"] for p in planes if planes[p]["evicted"] > 0}
        if stats["all"]["evicted"] > 0:
            evicted_by_ring["all"] = stats["all"]["evicted"]
        total_evicted = sum(evicted_by_ring.values())
        voices = collector.records[before:]

        check(
            total_evicted > 0,
            "L1 вытеснение есть",
            f"вытеснено {total_evicted} по кольцам {evicted_by_ring} (иначе судить нечего)",
        )
        with_digits = [v for v in voices if any(ch.isdigit() for ch in v)]
        check(
            len(voices) >= 1 and len(with_digits) == len(voices),
            "L2 голос прозвучал и несёт число",
            f"голосов {len(voices)}, из них с числом {len(with_digits)}",
        )
        check(
            0 < len(voices) <= len(evicted_by_ring),
            "L3 один голос на эпизод, не на запись",
            f"голосов {len(voices)} при {total_evicted} вытеснениях и {len(evicted_by_ring)} переполненных кольцах",
        )
        for text in voices:
            log(f"      голос: {text}")
    finally:
        try:
            drv.unwatch()
        except Exception as exc:  # noqa: BLE001 — уборка не должна прятать вердикт
            log(f"  (unwatch не удался: {exc})")
        drv.close()
        hub_logger.removeHandler(collector)

    log("")
    if _failures:
        log(f"ИТОГ: FAIL — {len(_failures)} проверок: {', '.join(_failures)}")
        return 1
    log("ИТОГ: OK — все проверки прошли")
    return 0


if __name__ == "__main__":
    sys.exit(main())
