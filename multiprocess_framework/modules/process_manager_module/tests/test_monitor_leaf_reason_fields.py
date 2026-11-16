# -*- coding: utf-8 -*-
"""fix-B4 / И2-1 (свежее ревью Ф1 run-state, итерация 2): поля ПРИЧИН листа готовности проверяются на входе.

F1 закрыл контейнеры (``reasons`` — список dict), но не поля внутри причины: ``severity: []`` ронял ``has_blocking``
(unhashable, оценка теряется, авария соседа не видна), ``node: ["a"]`` убивал поток остановки в аварии
(``_run_stop_finish``) и оставлял ``ack`` в ``fault_stopping`` навсегда.

Теперь одна функция контракта (``process_module.health.schema.readiness_reason_is_valid``) проверяет причину и у ребёнка
(константы шкалы и потолков общие), и у монитора (``normalize_leaf``). Выбор: негодная причина делает негодным ВЕСЬ лист
(лист заменяется одной причиной «лист готовности негоден: <процесс>»): контракт нарушен целиком, чинить лист по частям
нечем. Годный лист (в том числе на границах 200 символов и 32 причин) проходит без изменений.

Отдельно (б): ``fault_stop_done`` ставится в ``finally`` — сбой при дописывании причин срока не оставляет ``ack`` без
выхода. Обвязка — настоящие ``ProcessManagerProcess`` + ``ProcessMonitor`` (``make_readiness_pm``); ожидания — литералы.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from ...process_module.generic.plugin_orchestrator import PluginOrchestrator
from ...process_module.health.schema import readiness_reason_is_valid
from .test_run_commands import beat, make_readiness_pm

_INVALID = {"node": "a", "severity": "failure", "reason": "лист готовности негоден: a", "source": "report"}


def _reason(**fields: Any) -> dict:
    base: dict[str, Any] = {"node": "a.p", "severity": "failure", "reason": "x", "source": "readiness"}
    base.update(fields)
    return base


def _leaf(reasons: list) -> dict:
    return {"ready": True, "reasons": reasons, "paused": False, "at": time.time()}


def _send(monitor: Any, name: str, readiness: dict) -> None:
    monitor._on_heartbeat_received({"sender": name, "timestamp": time.time(), "readiness": readiness})


def _raw_tick(monitor: Any) -> None:
    with monitor._iteration_lock:
        monitor._run_iteration()


# --------------------------------------------------------------------------- #
# Таблица негодных полей: лист заменён, значений входа в нём нет
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(_reason(severity=[]), id="severity-list"),
        pytest.param(_reason(severity={}), id="severity-dict"),
        pytest.param(_reason(severity=5), id="severity-int"),
        pytest.param(_reason(severity=None), id="severity-none"),
        pytest.param(_reason(severity="SECRET-unknown"), id="severity-unknown-str"),
        pytest.param(_reason(node=["SECRET"]), id="node-list"),
        pytest.param(_reason(node=None), id="node-none"),
        pytest.param(_reason(node=5), id="node-int"),
        pytest.param(_reason(reason=5), id="reason-int"),
        pytest.param(_reason(reason=["SECRET"]), id="reason-list"),
        pytest.param(_reason(source=5), id="source-int"),
        pytest.param(_reason(source=None), id="source-none"),
        pytest.param(_reason(reason="SECRET" + "x" * 195), id="reason-201-chars"),
        pytest.param({"node": "a.p", "severity": "failure", "reason": "SECRET"}, id="source-missing"),
    ],
)
def test_bad_reason_field_makes_whole_leaf_invalid(bad: dict) -> None:
    """Одна причина с негодным полем: лист процесса заменён (``ready: false``, одна причина «лист готовности негоден:
    a»), значения входа (``SECRET``) в листе нет, соседняя годная причина того же листа тоже не принята."""
    _pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}})

    _send(monitor, "a", _leaf([_reason(reason="good"), bad]))

    leaf = monitor.readiness_snapshot()["a"]
    assert (leaf["ready"], leaf["reasons"]) == (False, [_INVALID]), leaf
    assert "SECRET" not in json.dumps(leaf, ensure_ascii=False)


@pytest.mark.timeout(60)
def test_too_many_reasons_makes_leaf_invalid() -> None:
    """33 причины (потолок 32): лист негоден; 10**4 причин не копится в мониторе."""
    _pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}})

    _send(monitor, "a", _leaf([_reason(reason=f"r{i}") for i in range(33)]))

    assert monitor.readiness_snapshot()["a"]["reasons"] == [_INVALID]


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "good",
    [
        pytest.param([_reason(reason="x" * 200)], id="reason-200-chars"),
        pytest.param([_reason(reason=f"r{i}") for i in range(32)], id="32-reasons"),
        pytest.param(
            [_reason(severity=s) for s in ("failure", "check_function", "out_of_spec", "maintenance")], id="scale"
        ),
    ],
)
def test_boundary_good_reasons_pass_unchanged(good: list) -> None:
    """Охрана: границы (200 символов, 32 причины, все четыре уровня шкалы) — годный лист принят как есть."""
    _pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}})
    sent = _leaf(good)

    _send(monitor, "a", dict(sent))

    assert monitor.readiness_snapshot()["a"] == sent


@pytest.mark.timeout(60)
def test_reason_built_by_child_orchestrator_is_valid_by_the_shared_function() -> None:
    """Один источник правды: причина, которую строит отправитель (``PluginOrchestrator._reason``), и маркер
    «причин больше 32» проходят ту же функцию, что у получателя."""
    built = PluginOrchestrator._reason("cam.p", "failure", "x" * 500)

    assert len(built["reason"]) == 200
    assert readiness_reason_is_valid(built) is True
    assert readiness_reason_is_valid({**built, "severity": "fatal"}) is False


# --------------------------------------------------------------------------- #
# R6: severity: [] не выключает обнаружение аварии соседа
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_r6_severity_list_does_not_blind_crash_detection() -> None:
    """``running`` (a, b); ``a`` шлёт причину ``severity: []``; ``b`` падает; 3 такта. До правки лист принимался, каждый
    такт бросал ``unhashable type: 'list'`` и состояние оставалось ``running``. Теперь — ``fault``; причины: негодный
    лист ``a`` и «процесс не жив» у ``b``; сбоев такта готовности в журнале нет."""
    pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}, "b": {"class": "pkg.B"}})
    beat(monitor, "a")
    beat(monitor, "b")
    _raw_tick(monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}

    _send(monitor, "a", _leaf([_reason(node="a", severity=[])]))
    proc_b = pm._process_registry.get_process_by_name("b")
    proc_b._alive = False
    proc_b.exitcode = -9
    pm._log_error.reset_mock()
    for _ in range(3):
        _raw_tick(monitor)

    assert pm._run_state == "fault", pm._run_state
    assert [(r["node"], r["reason"]) for r in pm._cmd_system_run_status()["reasons"]] == [
        ("a", "лист готовности негоден: a"),
        ("b", "процесс не жив"),
    ]
    tick_errors = [c.args[0] for c in pm._log_error.call_args_list if c.args and "readiness tick" in c.args[0]]
    assert tick_errors == [], tick_errors


# --------------------------------------------------------------------------- #
# R7: node: ["a"] не оставляет fault без выхода
# --------------------------------------------------------------------------- #


def _wait_ack_allowed(pm: Any, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if pm._cmd_system_run_status()["ack_allowed"] is True:
            return True
        time.sleep(0.02)
    return False


@pytest.mark.timeout(60)
def test_r7_node_list_in_reason_still_lets_fault_be_acknowledged() -> None:
    """``a`` шлёт причину ``node: ["a"]`` (``out_of_spec``), ``b`` отчитывается ``failure`` -> ``fault``. До правки
    причина с негодным ``node`` попадала в ``last_fault``, поток остановки в аварии умирал на ``TypeError``, ``ack``
    навсегда отвечал ``fault_stopping``. Теперь — ``ack_allowed`` становится истиной, ``ack`` -> ``ready`` невозможен
    лишь пока ``b`` не ``ok``, но ответ — не ``fault_stopping``."""
    pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}, "b": {"class": "pkg.B"}})
    pm.update_config("run_stop_timeout_s", 0.3)
    beat(monitor, "a")
    beat(monitor, "b")
    _raw_tick(monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}

    _send(monitor, "a", _leaf([_reason(node=["a"], severity="out_of_spec")]))
    beat(monitor, "b", ready=False, reasons=[_reason(node="b", reason="y")])
    _raw_tick(monitor)

    assert pm._run_state == "fault"
    assert _wait_ack_allowed(pm), pm._cmd_system_run_status()
    assert pm._cmd_system_run_ack().get("error") != "fault_stopping"


@pytest.mark.timeout(60)
def test_fault_stop_done_set_even_when_appending_timeout_reasons_raises() -> None:
    """Защита глубже входа: в ``last_fault`` оказалась причина с негодным полем (мимо монитора), процесс не подтвердил
    остановку — дописывание причин срока бросает. ``fault_stop_done`` всё равно становится истиной (``finally``),
    ``ack`` не залипает в ``fault_stopping``; сбой — один ERROR с типом исключения, без текста входа."""
    pm, monitor = make_readiness_pm({"a": {"class": "pkg.A"}, "b": {"class": "pkg.B"}})
    pm.update_config("run_stop_timeout_s", 0.3)
    beat(monitor, "a")
    beat(monitor, "b")
    _raw_tick(monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    with monitor._readiness_lock:  # лист мимо ``_admit_heartbeat``: так выглядит «ещё один путь записи»
        monitor._readiness["a"] = _leaf([_reason(node=["a"], severity="out_of_spec")])
    beat(monitor, "b", ready=False, reasons=[_reason(node="b", reason="y")])
    pm._log_error.reset_mock()

    _raw_tick(monitor)

    assert pm._run_state == "fault"
    assert _wait_ack_allowed(pm), pm._cmd_system_run_status()
    logged = [c.args[0] for c in pm._log_error.call_args_list if c.args]
    assert [m for m in logged if "не дописаны" in m] == ["остановка в аварии: причины срока не дописаны (TypeError)"]
