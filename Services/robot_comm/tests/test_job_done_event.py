"""Независимые RED acceptance-тесты Task 3.5 (Services) — событие `on_job_done` ядра робота.

Контракт лида: секция "Контракт лида 3.5 (2026-09-23, до тестера)", §1, в
plans/line-sim/phase-3-object-engine.md. `RobotSimCore.__init__` сегодня НЕ принимает
`on_job_done` вовсе — сам факт передачи этого kwarg-а обязан упасть (`TypeError`) до
реализации; это и есть RED для нового публичного параметра существующего класса.
"""

from __future__ import annotations

import pytest

from Services.modbus.sdk.datatypes import encode_int32
from Services.robot_comm.core.registers import (
    REG_FREE,
    REG_JOB_ECAP,
    REG_JOB_FLAG,
    REG_JOB_X,
    REG_JOB_Y,
    REG_STOP,
    STOP_IN_PLACE,
    XY_SCALE,
)
from Services.robot_comm.server.sim_core import RobotSimCore


def _raw_mm(mm: float) -> int:
    return int(round(mm * XY_SCALE)) & 0xFFFF


def _submit_job(core: RobotSimCore, *, x_mm: float, y_mm: float, ecap: int, word_order: str) -> None:
    core.write(REG_JOB_X, [_raw_mm(x_mm)])
    core.write(REG_JOB_Y, [_raw_mm(y_mm)])
    core.write(REG_JOB_ECAP, encode_int32(ecap, word_order=word_order))
    core.write(REG_JOB_FLAG, [1])


def test_event_once_at_completion_with_payload():
    """Ровно одно событие на задание, в момент REG_FREE 0->1 (не на приёме); payload —
    index с 1, x/y знаковые (JOB_X/JOB_Y / XY_SCALE); STOP во время задания отменяет
    событие; on_job_done=None не меняет старое поведение (регрессия)."""
    events: list[dict] = []
    core = RobotSimCore(on_job_done=events.append)

    _submit_job(core, x_mm=12.3, y_mm=-45.6, ecap=5000, word_order="little")

    core.tick()  # accept_ticks=1 по умолчанию: приём внутри этого же тика, FREE->0
    assert events == [], "события не должно быть на приёме — только на завершении"
    assert core.regs[REG_FREE] == 0

    core.tick()  # job_ticks=2: первый тик исполнения
    assert events == []

    core.tick()  # второй тик исполнения -> REG_FREE 0->1, событие ровно одно
    assert len(events) == 1
    assert core.regs[REG_FREE] == 1

    event = events[0]
    assert event["index"] == 1
    assert event["x_mm"] == pytest.approx(12.3)
    assert event["y_mm"] == pytest.approx(-45.6)
    assert event["ecap"] == 5000
    assert isinstance(event["t"], float)

    # STOP во время второго задания -> событие не приходит вовсе
    _submit_job(core, x_mm=1.0, y_mm=1.0, ecap=1, word_order="little")
    core.tick()  # приём -> job_countdown взведён, FREE=0
    core.write(REG_STOP, [STOP_IN_PLACE])
    core.tick()  # STOP гасит задание раньше завершения (FREE->1 сразу, countdown сброшен)
    core.tick()  # контрольный тик — событие уже не может появиться
    assert len(events) == 1, "STOP во время задания обязан отменить событие — новых быть не должно"

    # on_job_done=None -> поведение идентично побитово (обратная совместимость)
    core_no_cb = RobotSimCore()
    _submit_job(core_no_cb, x_mm=1.0, y_mm=1.0, ecap=1, word_order="little")
    core_no_cb.tick()
    core_no_cb.tick()
    core_no_cb.tick()
    assert core_no_cb.regs[REG_FREE] == 1


@pytest.mark.parametrize("word_order", ["little", "big"])
def test_ecap_decoded_from_two_words(word_order):
    """E_capture 106016 (>65535 — требует ОБА слова REG_JOB_ECAP/+1) -> event['ecap'] ==
    106016 для обоих word_order (до правки декодировалось бы одно слово -> 40480)."""
    events: list[dict] = []
    core = RobotSimCore(word_order=word_order, on_job_done=events.append)

    _submit_job(core, x_mm=0.0, y_mm=0.0, ecap=106016, word_order=word_order)

    core.tick()
    core.tick()
    core.tick()

    assert len(events) == 1
    assert events[0]["ecap"] == 106016
