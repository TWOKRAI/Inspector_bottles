# -*- coding: utf-8 -*-
"""Task 1.8 (L-9, ADR-PMM-037) — тесты-ловушки автора проводки ``stop_wait_idle`` в PM.

Приёмку (R7-R11) писал слепой тестер; здесь — то, что ломается тихо:
  * реестр настоящего ``ProcessManagerProcess`` получает именно ``_stop_wait_idle`` (иначе стоп снова
    ждёт ``time.sleep`` и L-9 возвращается, а все двойники остаются зелёными);
  * сбой ``pump_inbound`` пишется в лог ОДИН раз за жизнь PM, а не на каждом проходе (20 раз в секунду);
  * роутер читается в момент вызова: подмена ``router_manager`` после создания PM видна ожиданию;
  * ``ChildProcessStop`` без idle (умолчание) по-прежнему ждёт ``time.sleep`` — прежние вызывающие не затронуты.
"""

from __future__ import annotations

import time
from typing import Any

from ..core.child_process_stop import ChildProcessStop
from ..process.process_manager_process import ProcessManagerProcess


class _Router:
    def __init__(self, raises: bool = False) -> None:
        self.pump_calls = 0
        self._raises = raises

    def pump_inbound(self) -> int:
        self.pump_calls += 1
        if self._raises:
            raise RuntimeError("pump exploded")
        return 0


def _pm() -> tuple[ProcessManagerProcess, list[tuple[str, str]]]:
    pm = ProcessManagerProcess(config={"shutdown_timeout": 1.0})
    records: list[tuple[str, str]] = []
    pm._log_error = lambda message, *_a, **_k: records.append(("error", str(message))) or True  # type: ignore[method-assign]
    pm._log_warning = lambda message, *_a, **_k: records.append(("warning", str(message))) or True  # type: ignore[method-assign]
    return pm, records


def test_registry_of_real_pm_gets_its_stop_wait_idle() -> None:
    pm, _ = _pm()

    assert pm._process_registry.stop_wait_idle == pm._stop_wait_idle


def test_pump_failure_is_logged_once_across_many_waits() -> None:
    pm, records = _pm()
    router = _Router(raises=True)
    pm.router_manager = router

    for _ in range(5):
        pm._stop_wait_idle(0.01)

    assert router.pump_calls == 5, "pump должен звониться на каждом проходе, сбой не отключает вычерпывание"
    assert len(records) == 1, f"сбой pump дал {len(records)} записей на 5 проходов, ожидалась 1: {records}"


def test_router_is_read_at_call_time() -> None:
    pm, _ = _pm()
    pm._stop_wait_idle(0.01)  # роутера нет — только сон
    late = _Router()
    pm.router_manager = late

    pm._stop_wait_idle(0.01)

    assert late.pump_calls == 1, "роутер, поставленный после создания PM, не виден ожиданию стопа"


class _Alive:
    def __init__(self, lifetime_s: float) -> None:
        self._till = time.monotonic() + lifetime_s

    def is_alive(self) -> bool:
        return time.monotonic() < self._till

    def terminate(self) -> None:
        self._till = 0.0

    def kill(self) -> None:
        self._till = 0.0


class _Event:
    def set(self) -> None:
        pass


def test_child_stop_without_idle_still_waits_by_plain_sleep() -> None:
    proc: Any = _Alive(0.15)
    stop = ChildProcessStop({"W": proc}, {"W": _Event()})

    t0 = time.monotonic()
    done = stop.join_until(time.monotonic() + 5.0)

    assert done is True
    assert time.monotonic() - t0 >= 0.1, "ожидание без idle не спало: горячий цикл"
