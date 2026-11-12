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

from ..process import run_state as run_state_mod
from ..process.run_state import RunState, transition
from .test_run_commands import _failure_nodes, _reason, _to_running, beat, make_readiness_pm, tick

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


# --------------------------------------------------------------------------- #
# Task 1.3 (system-run-state) — агрегат готовности: слепые приёмочные тесты
#
# Контракт — DESIGN п.1 и п.3 ``plans/2026-10-27_system-run-state/tasks/1.3.md`` (``evaluate`` и ``fault``).
# Ожидаемые значения — литералы. ``evaluate`` берётся как атрибут модуля (а не ``from ... import``): пока функции
# нет, красным становится сам тест (``AttributeError``), а не сбор модуля со 196 прогонами таблицы 1.1.
#
# Решения тестера (ASSUMPTION; список — в отчёте, «ВОПРОС ЛИДУ»):
#   * ``leaves[name]`` — сам dict ``readiness`` (``{"ready", "reasons", "paused", "at"}``); нет ключа = нет листа;
#   * ``alive[name]`` — ``bool``; причина — dict с ключами ``severity`` / ``source`` / ``node``;
#   * в причинах-литералах ``message`` не проверяется (имя ключа текста в DESIGN не названо).
# --------------------------------------------------------------------------- #

_NOW = 1000.0
_STALE_S = 3.0


def _leaf(*, ready: bool = True, reasons: list[dict] | None = None, age_s: float = 0.0) -> dict:
    """Лист ``readiness`` процесса; ``at`` = ``_NOW - age_s``."""
    return {"ready": ready, "reasons": list(reasons or []), "paused": False, "at": _NOW - age_s}


def _failure(node: str, source: str = "plugin") -> dict:
    return {"severity": "failure", "source": source, "node": node, "message": f"{node}: failure"}


def _evaluate(expected: list[str], leaves: dict, alive: dict) -> tuple[bool, list[dict]]:
    return run_state_mod.evaluate(expected, leaves, alive, _NOW, _STALE_S)


def test_missing_leaf_is_not_ready_liveness_reason() -> None:
    """Листа нет (процесс не прислал ``readiness``) -> не готов; одна причина ``failure`` / ``liveness`` по узлу."""
    ready, reasons = _evaluate(["cam"], {}, {"cam": True})

    assert ready is False
    assert len(reasons) == 1, reasons
    assert reasons[0]["severity"] == "failure"
    assert reasons[0]["source"] == "liveness"
    assert reasons[0]["node"] == "cam"


@pytest.mark.parametrize("age_s", [3.5, 3600.0], ids=["just-over-stale_s", "an-hour-old"])
def test_stale_leaf_is_not_ready(age_s: float) -> None:
    """Лист, рассчитанный (``at``) раньше ``stale_s`` назад, — не готов, причина ``liveness`` по узлу;
    тот же лист со свежим ``at`` (2.5 с при ``stale_s`` 3 с) — готов без причин."""
    assert _evaluate(["cam"], {"cam": _leaf(age_s=2.5)}, {"cam": True}) == (True, [])  # свежий: контроль

    ready, reasons = _evaluate(["cam"], {"cam": _leaf(age_s=age_s)}, {"cam": True})

    assert ready is False
    assert len(reasons) == 1, reasons
    assert reasons[0]["severity"] == "failure"
    assert reasons[0]["source"] == "liveness"
    assert reasons[0]["node"] == "cam"


def test_live_process_without_report_is_not_ready() -> None:
    """Из двух живых процессов отчитался один: итог — не готов; причина ровно одна и только по молчащему."""
    ready, reasons = _evaluate(["cam", "rec"], {"cam": _leaf()}, {"cam": True, "rec": True})

    assert ready is False
    assert len(reasons) == 1, reasons
    assert reasons[0]["node"] == "rec"
    assert reasons[0]["severity"] == "failure"
    assert reasons[0]["source"] == "liveness"


def test_process_outside_recipe_not_required() -> None:
    """Процессы вне ``expected`` (чужой лист ``ready: false``, мёртвый, без листа) на готовность не влияют."""
    leaves = {
        "cam": _leaf(),
        "stranger": _leaf(ready=False, reasons=[_failure("stranger")]),
        "stale_ghost": _leaf(age_s=3600.0),
    }
    alive = {"cam": True, "stranger": False, "stale_ghost": False, "no_leaf_ghost": False}

    assert _evaluate(["cam"], leaves, alive) == (True, [])


@pytest.mark.parametrize(
    ("leaf_reasons", "expected_sources"),
    [
        pytest.param([], ["report"], id="no-reasons"),
        pytest.param(
            [{"severity": "out_of_spec", "source": "plugin", "node": "cam"}],
            ["plugin", "report"],
            id="only-out_of_spec",
        ),
        pytest.param([_failure("cam.detect")], ["plugin"], id="own-failure-not-duplicated"),
    ],
)
def test_fresh_leaf_not_ready_without_reasons_is_failure(leaf_reasons: list[dict], expected_sources: list[str]) -> None:
    """Свежий лист ``ready: false`` без собственной ``failure`` -> процесс не готов, добавлена ``failure`` /
    ``report`` по узлу (причины листа сохранены); с собственной ``failure`` — ничего не добавляется."""
    ready, reasons = _evaluate(["cam"], {"cam": _leaf(ready=False, reasons=leaf_reasons)}, {"cam": True})

    assert ready is False
    assert sorted(r["source"] for r in reasons) == sorted(expected_sources), reasons
    assert any(r["severity"] == "failure" for r in reasons), reasons
    if "report" in expected_sources:
        added = [r for r in reasons if r["source"] == "report"]
        assert len(added) == 1 and added[0]["severity"] == "failure" and added[0]["node"] == "cam", reasons


# --------------------------------------------------------------------------- #
# Потеря готовности в running -> fault (PM с настоящим монитором, см. test_run_commands.py)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_running_loses_readiness_goes_fault() -> None:
    """``running``; процесс шлёт СВЕЖИЕ heartbeat, но его снимок готовности (``readiness.at``) остановился
    (мёртвый поток-наблюдатель при живом heartbeat) -> такт -> ``fault``, причина ``failure`` по узлу."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _to_running(pm, monitor)

    beat(monitor, "cam", age_s=3600.0)  # heartbeat сейчас, снимок часовой давности
    tick(pm, monitor)

    assert pm._run_state == "fault"
    status = pm._cmd_system_run_status()
    assert status["state"] == "fault", status
    assert _failure_nodes(status["reasons"]) == ["cam"], status
    assert status["reasons"][0]["source"] == "liveness", status


@pytest.mark.timeout(60)
def test_fault_stays_fault_when_readiness_returns() -> None:
    """После ``fault`` готовность вернулась (свежий отчёт ``ready: true``, несколько тактов) — состояние остаётся
    ``fault``, START отказан ``fault_unacknowledged``, ``run_event`` снято; выход из ``fault`` — не по готовности."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _to_running(pm, monitor)
    beat(monitor, "cam", ready=False, reasons=[_reason("failure", "cam")])
    tick(pm, monitor)
    assert pm._run_state == "fault"

    for _ in range(3):  # несколько тактов подряд со свежим отчётом о готовности
        beat(monitor, "cam", ready=True)
        tick(pm, monitor)

    assert pm._run_state == "fault"
    status = pm._cmd_system_run_status()
    assert status["state"] == "fault" and status["start_allowed"] is False, status
    reply = pm._cmd_system_run_start()
    assert reply["success"] is False and reply["state"] == "fault", reply
    assert reply["error"] == "fault_unacknowledged", reply
    assert pm._run_state == "fault"
    assert pm._run_event.is_set() is False
