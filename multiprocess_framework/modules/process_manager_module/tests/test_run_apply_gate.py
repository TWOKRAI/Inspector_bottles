# -*- coding: utf-8 -*-
"""Task 1.5 (system-run-state) — слепые приёмочные тесты гейта ``topology.apply`` по состоянию работы (7 функций).

Написано ДО реализации по наблюдаемым требованиям брифа (DESIGN/FILES, ``plans/**`` и отчёты не читались).

Контракт (из брифа): ``topology.apply`` (``_cmd_topology_apply``) в состоянии ``running`` / ``stopping`` / ``fault`` /
``shutting_down`` отказывает БЕЗ побочных эффектов (топология, процессы, ``run_event``, ``last_fault`` не меняются):
``{"success": False, "error": <имя>, "message": ...}``. Коды: ``running`` -> ``running`` («сначала ОСТАНОВИТЬ»);
``stopping`` -> ``stopping`` («сначала ОСТАНОВИТЬ»); ``fault`` -> ``fault_unacknowledged`` («сначала Квитировать»);
``shutting_down`` -> ``shutting_down``. В ``ready`` / ``not_ready`` apply проходит как раньше: машина идёт в
``booting`` и после применения — в ``ready``/``not_ready`` по оценке готовности; ``run_event`` остаётся снятым
(система в работу сама не уходит). Прямой вызов обработчика и вызов через исполнитель ``pm-lifecycle`` дают один и тот
же отказ; отказ быстрый.

Обвязка — настоящие объекты, как в ``test_run_commands.py`` / ``test_apply_topology.py``: ``make_readiness_pm``
(``make_pm`` + настоящий ``_create_components`` под патчем реестра + настоящий ``ProcessMonitor``; реестр процессов и
планировщик топологии — двойники ``conftest``, apply проходит по-настоящему). Состояния машины выставляются единственной
точкой записи ``pm._run_apply(<событие>)`` (как в ``make_run_pm``), без запуска последовательностей STOP/аварии.

Допущения тестера (полный список — в отчёте):
  * ответ — ``dict`` с ключами ``success`` / ``error`` / ``message``; прочие ключи не сверяются;
  * текст ``message`` проверяется подстрокой («сначала ОСТАНОВИТЬ» / «сначала Квитировать»); у ``shutting_down`` текст
    не проверяется (в брифе его нет);
  * «побочные эффекты» = ``_process_configs`` PM, набор объектов процессов реестра, ``run_event``, ``last_fault``,
    состояние машины, число ``broadcast`` (раздача слоя рецепта детям);
  * путь через исполнитель: настоящий ``ExecutorManager`` + ``pm._setup_lifecycle_executor()`` + настоящий
    ``CommandManager`` с регистрацией встроенных команд PM; ответ приходит в ``reply``.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

import pytest

from ...command_module import CommandManager
from ...worker_module import WorkerManager
from ...worker_module.executor_manager import ExecutorManager
from ..process.process_manager_process import ProcessManagerProcess
from .conftest import wire_planner
from .test_run_commands import make_readiness_pm

_DEADLINE_S = 10.0  # потолок любого ожидания: дальше «не дождались» = упавший ассерт
_FAST_S = 3.0  # отказ — быстрый: ни ожидания исполнителя, ни apply

# новая топология, которую apply обязан применить в ready/not_ready и обязан НЕ тронуть при отказе
_NEW_TOPOLOGY = {"processes": [{"process_name": "n1", "process_class": "m.N1"}]}
_APPLY_ARGS = {"topology_dict": _NEW_TOPOLOGY, "recipe_path": "recipes/recipe_b.yaml"}

# (состояние, код отказа, подстрока message | None) — литералы из требований
_REFUSALS = {
    "running": ("running", "сначала ОСТАНОВИТЬ"),
    "stopping": ("stopping", "сначала ОСТАНОВИТЬ"),
    "fault": ("fault_unacknowledged", "сначала Квитировать"),
    "shutting_down": ("shutting_down", None),
}


def _bounded(fn: Any, deadline_s: float = _DEADLINE_S) -> Any:
    """Вызвать ``fn`` в daemon-потоке с join-дедлайном: зависший вызов — упавший ассерт, не зависший прогон."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name="apply-gate-bounded")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _pm_in(state: str) -> ProcessManagerProcess:
    """PM с одним процессом топологии ``w1``; машина доведена до ``state`` событиями ``_run_apply``."""
    pm, _monitor = make_readiness_pm({"w1": {"class": "m.W1"}})
    # ``_create_components`` обнуляет менеджер топологии (его строит ``initialize``): поднимаем как ``make_pm``
    pm._setup_topology_manager()
    wire_planner(pm)
    pm._ensure_routing_state()  # routing-состояние ставит боевой ``__init__``; нужно apply и адаптеру исполнителя
    assert pm._run_snapshot()[0].value == "ready"  # итог boot-барьера
    if state == "ready":
        return pm
    if state == "not_ready":
        pm._run_apply("tick", ready=False)
    elif state == "shutting_down":
        pm._run_apply("shutdown")
    else:
        pm._run_apply("start", ready=True)  # running: событие взведено
        if state == "stopping":
            pm._run_apply("stop")
        elif state == "fault":
            pm._run_apply("tick", ready=False)  # потеря готовности в running
        else:
            assert state == "running", state
    assert pm._run_snapshot()[0].value == state, pm._run_snapshot()
    return pm


def _effects(pm: ProcessManagerProcess) -> dict[str, Any]:
    """Всё, что отказанный apply не имеет права изменить (наблюдаемое, не имена внутренних вызовов)."""
    registry = pm._process_registry
    return {
        "configs": copy.deepcopy(pm._process_configs),
        "processes": {name: id(proc) for name, proc in registry._processes.items()},
        "event": pm._run_event.is_set(),
        "last_fault": copy.deepcopy(pm._cmd_system_run_status()["last_fault"]),
        "state": pm._run_snapshot()[0].value,
        "broadcasts": pm.communication.broadcast.call_count,
    }


def _apply(pm: ProcessManagerProcess) -> dict:
    reply = _bounded(lambda: pm._cmd_topology_apply(copy.deepcopy(_APPLY_ARGS)))
    assert isinstance(reply, dict), reply
    return reply


def _assert_refused(reply: dict, error: str, message_part: str | None) -> None:
    assert reply.get("success") is False, reply
    assert reply.get("error") == error, reply
    if message_part is not None:
        assert message_part in str(reply.get("message")), reply


# --------------------------------------------------------------------------- #
# 1-4. Отказ в каждом из четырёх состояний со своим кодом и текстом
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_apply_in_running_refused_running() -> None:
    """``running``: apply -> ``{"success": False, "error": "running", "message": «сначала ОСТАНОВИТЬ»}``."""
    pm = _pm_in("running")

    _assert_refused(_apply(pm), *_REFUSALS["running"])


@pytest.mark.timeout(60)
def test_apply_in_stopping_refused_stopping() -> None:
    """``stopping``: apply -> error ``stopping``, message «сначала ОСТАНОВИТЬ»; машина остаётся в ``stopping``."""
    pm = _pm_in("stopping")

    _assert_refused(_apply(pm), *_REFUSALS["stopping"])
    assert pm._run_snapshot()[0].value == "stopping"


@pytest.mark.timeout(60)
def test_apply_in_fault_refused_unacknowledged() -> None:
    """``fault``: apply -> error ``fault_unacknowledged``, message «сначала Квитировать»; авария не снята."""
    pm = _pm_in("fault")

    _assert_refused(_apply(pm), *_REFUSALS["fault"])
    assert pm._run_snapshot()[0].value == "fault"


@pytest.mark.timeout(60)
def test_apply_in_shutting_down_refused() -> None:
    """``shutting_down``: apply -> error ``shutting_down``; машина остаётся в ``shutting_down``."""
    pm = _pm_in("shutting_down")

    _assert_refused(_apply(pm), *_REFUSALS["shutting_down"])
    assert pm._run_snapshot()[0].value == "shutting_down"


# --------------------------------------------------------------------------- #
# 5. Проход в ready / not_ready: booting -> ready|not_ready, в работу сама не уходит
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("before", ["ready", "not_ready"])
def test_apply_in_ready_goes_booting_not_running(before: str) -> None:
    """В ``ready``/``not_ready`` apply проходит (``success`` True, топология заменена): на время применения машина в
    ``booting``, после — ``ready``/``not_ready`` по оценке; ``run_event`` снят всё время, ``running`` не бывает."""
    pm = _pm_in(before)
    seen: list[tuple[str, bool]] = []
    real_apply = pm.apply_topology

    def spy(blueprint: Any) -> dict:
        seen.append((pm._run_snapshot()[0].value, pm._run_event.is_set()))
        return real_apply(blueprint)

    pm.apply_topology = spy

    reply = _apply(pm)

    assert reply.get("success") is True, reply
    assert "n1" in pm._process_configs, sorted(pm._process_configs)  # топология заменена
    assert seen == [("booting", False)], seen  # применение шло в booting, событие снято
    assert pm._run_snapshot()[0].value in ("ready", "not_ready"), pm._run_snapshot()
    assert pm._run_event.is_set() is False


# --------------------------------------------------------------------------- #
# 6. Отказ без побочных эффектов (во всех четырёх состояниях)
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
@pytest.mark.parametrize("state", ["running", "stopping", "fault", "shutting_down"])
def test_refused_apply_has_no_side_effects(state: str) -> None:
    """Отказанный apply ничего не меняет: топология PM, набор объектов процессов, ``run_event``, ``last_fault``,
    состояние машины, раздача слоя рецепта детям (``broadcast``) — как до вызова. Сам отказ при этом есть."""
    pm = _pm_in(state)
    before = _effects(pm)

    reply = _apply(pm)

    assert reply.get("success") is False, reply
    assert reply.get("error") == _REFUSALS[state][0], reply
    after = _effects(pm)
    assert after == before, {k: (before[k], after[k]) for k in before if before[k] != after[k]}


# --------------------------------------------------------------------------- #
# 7. Один отказ на двух путях вызова; отказ быстрый
# --------------------------------------------------------------------------- #


def _lifecycle_wired(pm: ProcessManagerProcess) -> tuple[CommandManager, Any, Any]:
    """Настоящий ``pm-lifecycle`` + ``CommandManager`` со встроенными командами PM (``topology.apply`` — класс L)."""
    worker_manager = WorkerManager(manager_name="apply-gate", process=None)
    assert worker_manager.initialize() is True
    manager = ExecutorManager("apply-gate_executors", worker_manager=worker_manager)
    assert manager.initialize() is True
    pm.executor_manager = manager
    assert pm._setup_lifecycle_executor() is True
    command_manager = CommandManager("apply-gate-cm", executors=manager)
    pm.command_manager = command_manager
    pm._register_builtin_commands()
    return command_manager, manager, worker_manager


@pytest.mark.timeout(60)
def test_refusal_same_direct_and_via_lifecycle_executor_and_fast() -> None:
    """В ``running`` прямой вызов обработчика и ``topology.apply`` через ``pm-lifecycle`` (настоящий
    ``CommandManager`` + исполнитель, ответ в ``reply``) дают ОДИН отказ ``running``; оба быстрее ``_FAST_S``;
    после обоих топология и ``run_event`` прежние (отказ не прошёл «боком» через исполнитель)."""
    pm = _pm_in("running")
    command_manager, executor_manager, worker_manager = _lifecycle_wired(pm)
    before = _effects(pm)
    try:
        t0 = time.monotonic()
        direct = _bounded(lambda: pm._cmd_topology_apply(copy.deepcopy(_APPLY_ARGS)))
        direct_s = time.monotonic() - t0

        replies: list[Any] = []
        got = threading.Event()

        def reply(result: Any) -> None:
            replies.append(result)
            got.set()

        t1 = time.monotonic()
        command_manager.handle_command({"command": "topology.apply", "data": copy.deepcopy(_APPLY_ARGS)}, reply=reply)
        assert got.wait(_DEADLINE_S), "ответ topology.apply через pm-lifecycle не пришёл за дедлайн"
        via_s = time.monotonic() - t1

        _assert_refused(direct, *_REFUSALS["running"])
        _assert_refused(replies[0], *_REFUSALS["running"])
        assert direct.get("error") == replies[0].get("error"), (direct, replies[0])
        assert direct.get("message") == replies[0].get("message"), (direct, replies[0])
        assert direct_s < _FAST_S, f"прямой отказ занял {direct_s:.2f} с"
        assert via_s < _FAST_S, f"отказ через исполнитель занял {via_s:.2f} с"
        assert _effects(pm) == before
    finally:
        for stop in (executor_manager.shutdown, worker_manager.shutdown):
            thread = threading.Thread(target=stop, daemon=True)
            thread.start()
            thread.join(10.0)
