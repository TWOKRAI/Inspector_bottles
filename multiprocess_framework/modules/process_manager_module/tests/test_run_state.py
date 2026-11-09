# -*- coding: utf-8 -*-
"""Task 1.1 (system-run-state) — слепой тест таблицы переходов ``transition()``.

Контракт — DESIGN п.1 ``plans/2026-10-27_system-run-state/tasks/1.1.md`` и design.md §3.2.
Все ожидаемые значения — литералы ячеек таблицы 7x7 (состояние x событие), переписанные по ячейкам;
ни одна не выводится из кода под тестом. ``R`` = ``ready`` при ``ready=True``, иначе ``not_ready``.

Решения тестера:
  * ASSUMPTION: событие передаётся обычной строкой (``"start"``), не членом перечисления;
  * ASSUMPTION: имена членов ``RunState`` — строчные, как в ``_run_state = RunState.booting`` (DESIGN п.2);
    вход строится по значению (``RunState("ready")``), результат сравнивается со строковым литералом
    (``RunState(str, Enum)`` равен своему строковому значению);
  * неизвестное событие — отдельная группа параметров (по одному на состояние), ожидание ``ValueError``.
"""

from __future__ import annotations

import pytest

from ..process.run_state import RunState, transition

STATES = ["booting", "not_ready", "ready", "running", "stopping", "fault", "shutting_down"]
EVENTS = ["start", "stop", "ack", "apply", "shutdown", "settled", "tick"]
COMBOS = [(False, False), (False, True), (True, False), (True, True)]  # (ready, stop_done)


def _same(cell: tuple[str, str | None]) -> dict[tuple[bool, bool], tuple[str, str | None]]:
    """Ячейка не зависит от (ready, stop_done): один и тот же литерал для всех четырёх комбинаций."""
    return {combo: cell for combo in COMBOS}


def _by_ready(
    ready_cell: tuple[str, str | None], not_ready_cell: tuple[str, str | None]
) -> dict[tuple[bool, bool], tuple[str, str | None]]:
    """Ячейка зависит только от ``ready``: ``stop_done`` игнорируется."""
    return {(r, s): (ready_cell if r else not_ready_cell) for r, s in COMBOS}


#: Таблица 7x7 литералом по ячейкам: TABLE[состояние][событие] -> {(ready, stop_done): (новое состояние, код)}.
TABLE: dict[str, dict[str, dict[tuple[bool, bool], tuple[str, str | None]]]] = {
    "booting": {
        "start": _same(("booting", "not_ready")),
        "stop": _same(("booting", None)),
        "ack": _same(("booting", "no_fault")),
        "apply": _same(("booting", None)),
        "shutdown": _same(("shutting_down", None)),
        "settled": _by_ready(("ready", None), ("not_ready", None)),
        "tick": _same(("booting", None)),
    },
    "not_ready": {
        "start": _same(("not_ready", "not_ready")),
        "stop": _same(("not_ready", None)),
        "ack": _same(("not_ready", "no_fault")),
        "apply": _same(("booting", None)),
        "shutdown": _same(("shutting_down", None)),
        "settled": _same(("not_ready", None)),
        "tick": _by_ready(("ready", None), ("not_ready", None)),
    },
    "ready": {
        "start": _by_ready(("running", None), ("not_ready", "not_ready")),
        "stop": _same(("ready", None)),
        "ack": _same(("ready", "no_fault")),
        "apply": _same(("booting", None)),
        "shutdown": _same(("shutting_down", None)),
        "settled": _same(("ready", None)),
        "tick": _by_ready(("ready", None), ("not_ready", None)),
    },
    "running": {
        "start": _same(("running", "already_running")),
        "stop": _same(("stopping", None)),
        "ack": _same(("running", "no_fault")),
        "apply": _same(("running", "running")),
        "shutdown": _same(("shutting_down", None)),
        "settled": _same(("running", None)),
        "tick": _by_ready(("running", None), ("fault", None)),
    },
    "stopping": {
        "start": _same(("stopping", "stopping")),
        "stop": _same(("stopping", None)),
        "ack": _same(("stopping", "no_fault")),
        "apply": _same(("stopping", "stopping")),
        "shutdown": _same(("shutting_down", None)),
        "settled": _by_ready(("ready", None), ("not_ready", None)),
        "tick": _same(("stopping", None)),
    },
    "fault": {
        "start": _same(("fault", "fault_unacknowledged")),
        "stop": _same(("fault", None)),
        # ack в fault: stop_done=True -> R; stop_done=False -> отказ fault_stopping (ready не читается)
        "ack": {
            (False, False): ("fault", "fault_stopping"),
            (True, False): ("fault", "fault_stopping"),
            (False, True): ("not_ready", None),
            (True, True): ("ready", None),
        },
        "apply": _same(("fault", "fault_unacknowledged")),
        "shutdown": _same(("shutting_down", None)),
        "settled": _same(("fault", None)),
        "tick": _same(("fault", None)),
    },
    "shutting_down": {
        "start": _same(("shutting_down", "shutting_down")),
        "stop": _same(("shutting_down", "shutting_down")),
        "ack": _same(("shutting_down", "shutting_down")),
        "apply": _same(("shutting_down", "shutting_down")),
        "shutdown": _same(("shutting_down", None)),
        "settled": _same(("shutting_down", None)),
        "tick": _same(("shutting_down", None)),
    },
}

#: 49 ячеек x 4 комбинации (ready, stop_done) = 196 прогонов.
TABLE_CASES = [
    pytest.param(
        state,
        event,
        ready,
        stop_done,
        TABLE[state][event][(ready, stop_done)],
        id=f"{state}-{event}-r{int(ready)}s{int(stop_done)}",
    )
    for state in STATES
    for event in EVENTS
    for ready, stop_done in COMBOS
]
assert len(TABLE_CASES) == 196  # страж самой таблицы: 7 x 7 x 4

#: Неизвестное событие -> ValueError("unknown event") во всех семи состояниях (по одному прогону).
UNKNOWN_CASES = [
    pytest.param(state, "bogus-evt-xyz", True, False, ValueError, id=f"{state}-unknown") for state in STATES
]


@pytest.mark.parametrize(("state", "event", "ready", "stop_done", "expected"), TABLE_CASES + UNKNOWN_CASES)
def test_transition_table(state: str, event: str, ready: bool, stop_done: bool, expected) -> None:
    """Каждая ячейка таблицы §3.2 при каждой комбинации (ready, stop_done) даёт ровно литерал ячейки."""
    current = RunState(state)
    if expected is ValueError:
        with pytest.raises(ValueError, match="unknown event") as excinfo:
            transition(current, event, ready=ready, stop_done=stop_done)
        # Тексты ошибок без входных значений (ADR-PMM-044 п.1): ни событие, ни состояние в сообщение не попадают.
        assert "bogus-evt-xyz" not in str(excinfo.value)
        return

    result = transition(current, event, ready=ready, stop_done=stop_done)
    assert isinstance(result, tuple) and len(result) == 2, result
    new_state, code = result
    assert isinstance(new_state, RunState), type(new_state)
    assert (new_state, code) == expected, f"{state} + {event} (ready={ready}, stop_done={stop_done})"
    if not stop_done:
        # stop_done по умолчанию False: вызов без аргумента даёт тот же результат
        assert transition(current, event, ready=ready) == result
