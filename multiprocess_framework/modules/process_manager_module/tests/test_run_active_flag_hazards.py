# -*- coding: utf-8 -*-
"""Task 2.7d (system-run-state) — тесты опасностей автора: флаг ``run_active`` и запертые команды плагина.

REDS 8-10 текста ``tasks/2.7d.md``:
  8. Команда с исполнителем: флаг читается на потоке исполнителя, а не при постановке.
  9. Порядок в ``_run_apply``: флаг меняется под ``_run_lock`` ДО записи ``_run_state`` (журнал порядка и серия гонки).
  10. Шаги ``pre_stop``: STOP оператора (``stopping``) и graceful ``system.shutdown`` из ``running`` — охраняемый шаг
      исполняется; поздние такт и START посреди прохода флаг не взводят.

Плагин — настоящие объекты (``PluginOrchestrator`` + ``CommandManager`` + ``MockProcessServices``), вызов только
через ``cm.handle_command``. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable

import pytest

from ...command_module.core.command_manager import DEFERRED, CommandManager
from ...process_module.generic.plugin_orchestrator import PluginOrchestrator
from ...process_module.plugins.base import PluginContext, ProcessModulePlugin
from ...process_module.plugins.testing import MockProcessServices
from ..core.run_flag import RunFlag
from ..process.pre_stop import PreStopStep
from ..process.process_manager_process import _ChildrenStop
from .test_run_commands import make_run_pm
from .test_run_stop import _DEADLINE_S, _Rig, _StepRouter, _bounded, _wait

_THIS = "multiprocess_framework.modules.process_manager_module.tests.test_run_active_flag_hazards"
_REFUSAL = {"status": "error", "error": "running", "message": "сначала ОСТАНОВИТЬ"}
_SERIES_RUNS = 600
_SERIES_THREADS = 20


# --------------------------------------------------------------------------- #
# Харнесс плагина
# --------------------------------------------------------------------------- #


class _HeldExecutor:
    """Двойник ``OrderedExecutor``: ``submit`` только запоминает; ``run_held`` исполняет на потоке ``guard-exec``."""

    name = "guard-exec"

    def __init__(self) -> None:
        self.held: list[tuple[Callable[[], Any], Callable[[Any], None]]] = []

    def submit(self, action: Callable[[], Any], key: Any, reply: Callable[[Any], None]) -> bool:
        self.held.append((action, reply))
        return True

    def run_held(self) -> None:
        action, reply = self.held.pop(0)
        th = threading.Thread(target=lambda: reply(action()), daemon=True, name="guard-exec")
        th.start()
        th.join(_DEADLINE_S)
        assert not th.is_alive(), "исполнитель завис"


class ExecGuardPlugin(ProcessModulePlugin):
    """Двойник плагина: ``release_device`` — на исполнителе (``targets="all"``), счётчик и поток вызова."""

    name = "exec_guard"
    category = "processing"
    commands = {"release_device": "cmd_release_device"}
    executor = _HeldExecutor()

    def __init__(self) -> None:
        super().__init__()
        self.release_calls = 0
        self.release_threads: list[str] = []

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items

    def command_options(self, command_name: str) -> dict[str, Any]:
        return {"executor": type(self).executor, "targets": "all"}

    def cmd_release_device(self, data: dict) -> dict:
        self.release_calls += 1
        self.release_threads.append(threading.current_thread().name)
        return {"status": "ok", "released": True}


class ParkPlugin(ProcessModulePlugin):
    """Двойник плагина узла робота: шаг ``pre_stop`` ``robot_park_all`` — запертая команда."""

    name = "park"
    category = "processing"
    commands = {"robot_park_all": "cmd_park_all"}

    def __init__(self) -> None:
        super().__init__()
        self.park_calls = 0

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def process(self, items):
        return items

    def cmd_park_all(self, data: dict) -> dict:
        self.park_calls += 1
        return {"status": "ok", "parked": True}


class _PluginRig:
    def __init__(self, plugin_cls: type, locked: list[str], flag: Any) -> None:
        services = MockProcessServices(name="hazard_node")
        cm = CommandManager("hazard_cm")
        cm.initialize()
        services.command_manager = cm
        services._run_active = flag
        pdef = {
            "plugin_class": f"{_THIS}.{plugin_cls.__name__}",
            "plugin_name": plugin_cls.name,
            "config": {"run_locked_commands": locked},
        }
        self.orch = PluginOrchestrator(services=services)
        self.orch.load_and_configure_managers([pdef])
        self.orch.boot()
        self.cm = cm
        self.flag = flag

    @property
    def plugin(self) -> Any:
        return self.orch.plugins[0]

    def call(self, command: str, **kwargs: Any) -> Any:
        return self.cm.handle_command({"command": command, "data": {}}, **kwargs)


# --------------------------------------------------------------------------- #
# 8. Команда с исполнителем: флаг читается на исполнении
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_executor_command_reads_flag_on_executor_thread() -> None:
    """Постановка при СНЯТОМ флаге, ``set()`` до исполнения -> отказ литералом на потоке исполнителя, метод не вызван.
    Обратно: постановка при ВЗВЕДЁННОМ, ``clear()`` до исполнения -> команда исполнена на ``guard-exec``."""

    def scenario() -> None:
        ExecGuardPlugin.executor = _HeldExecutor()
        rig = _PluginRig(ExecGuardPlugin, ["release_device"], RunFlag())
        replies: list[tuple[Any, str]] = []

        def reply(result: Any) -> None:
            replies.append((result, threading.current_thread().name))

        assert rig.call("release_device", reply=reply) is DEFERRED
        rig.flag.set()
        ExecGuardPlugin.executor.run_held()
        assert replies == [(_REFUSAL, "guard-exec")], replies
        assert rig.plugin.release_calls == 0

        assert rig.call("release_device", reply=reply) is DEFERRED
        rig.flag.clear()
        ExecGuardPlugin.executor.run_held()
        assert replies[1] == ({"status": "ok", "released": True}, "guard-exec"), replies
        assert rig.plugin.release_calls == 1
        assert rig.plugin.release_threads == ["guard-exec"]

    _bounded(scenario, _DEADLINE_S)


# --------------------------------------------------------------------------- #
# 9. Порядок: флаг под _run_lock и ДО записи _run_state
# --------------------------------------------------------------------------- #


class _OrderSpy:
    """Обёртка над ``RunFlag`` PM: на ``set()``/``clear()`` пишет ``(операция, состояние в этот миг, замок занят)``."""

    def __init__(self, pm: Any, inner: RunFlag) -> None:
        self._pm = pm
        self._inner = inner
        self.log: list[tuple[str, str, bool]] = []

    def _note(self, op: str) -> None:
        self.log.append((op, str(self._pm._run_state.value), self._pm._run_lock.locked()))

    def set(self) -> None:
        self._note("set")
        self._inner.set()

    def clear(self) -> None:
        self._note("clear")
        self._inner.clear()

    def is_set(self) -> bool:
        return self._inner.is_set()


@pytest.mark.timeout(60)
@pytest.mark.parametrize("run_gate", [True, False])
def test_flag_written_under_run_lock_before_state(run_gate: bool) -> None:
    """Каждая смена флага — под ``_run_lock`` и ДО записи нового ``_run_state``: на ``set()`` состояние ещё ``ready``,
    на ``clear()`` в STOP и в аварии — ещё ``running``. Флаг доводится и после ``ack``."""
    pm = make_run_pm(run_gate)
    spy = _OrderSpy(pm, pm._run_active)
    pm._run_active = spy

    assert pm._cmd_system_run_start()["success"] is True
    pm._run_apply("stop")
    pm._run_apply("settled", ready=True)
    assert pm._cmd_system_run_start()["success"] is True
    pm._run_apply("tick", ready=False)
    assert pm._run_state == "fault"
    pm._run_apply("ack", stop_done=True)
    assert pm._run_state == "not_ready"

    assert spy.log == [
        ("set", "ready", True),
        ("clear", "running", True),
        ("set", "ready", True),
        ("clear", "running", True),
    ], spy.log
    assert spy.is_set() is False


@pytest.mark.timeout(300)
def test_observer_seeing_running_sees_flag_set_series() -> None:
    """Серия гонки (REDS 9): свежий PM на прогон, 20 потоков (START, такты ``ready=True`` и наблюдатели),
    ``sys.setswitchinterval(1e-6)``. Наблюдатель читает ``_run_state``, затем флаг: увидел ``running`` — флаг взведён.
    STOP и ``fault`` в фазе наблюдателя не подаются: флаг не снимается. Пары STOP и ``fault`` — последовательно."""
    violations: list[tuple[int, str]] = []
    errors: list[BaseException] = []
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for run in range(_SERIES_RUNS):
            pm = make_run_pm(True)
            flag = pm._run_active
            barrier = threading.Barrier(_SERIES_THREADS)

            def writer(i: int, pm: Any = pm, barrier: threading.Barrier = barrier) -> None:
                barrier.wait(_DEADLINE_S)
                if i % 3 == 0:
                    pm._cmd_system_run_start()
                else:
                    pm._run_apply("tick", ready=True)

            def observer(run: int = run, pm: Any = pm, flag: Any = flag, barrier: threading.Barrier = barrier) -> None:
                barrier.wait(_DEADLINE_S)
                end = time.monotonic() + 2.0
                while time.monotonic() < end:
                    state = pm._run_state
                    seen = flag.is_set()
                    if state == "running":
                        if not seen:
                            violations.append((run, "running при снятом флаге"))
                        return

            def guarded(fn: Callable[[], None]) -> Callable[[], None]:
                def go() -> None:
                    try:
                        fn()
                    except BaseException as exc:  # noqa: BLE001 — в поток теста
                        errors.append(exc)

                return go

            threads = [
                threading.Thread(target=guarded(lambda i=i: writer(i)), daemon=True, name=f"w{i}") for i in range(8)
            ]
            threads += [
                threading.Thread(target=guarded(observer), daemon=True, name=f"o{i}")
                for i in range(_SERIES_THREADS - 8)
            ]
            for th in threads:
                th.start()
            for th in threads:
                th.join(_DEADLINE_S)
                assert not th.is_alive(), f"прогон {run}: поток {th.name} завис"
            assert pm._run_state == "running", f"прогон {run}: START не прошёл"
            assert flag.is_set() is True
    finally:
        sys.setswitchinterval(old)
    assert errors == [], errors[:3]
    bad_runs = len({run for run, _ in violations})
    assert violations == [], f"прогонов с нарушением {bad_runs} из {_SERIES_RUNS} (наблюдений {len(violations)})"

    pm = make_run_pm(True)
    assert pm._cmd_system_run_start()["success"] is True
    pm._run_apply("stop")
    assert (pm._run_state, pm._run_active.is_set()) == ("stopping", False)
    pm = make_run_pm(True)
    assert pm._cmd_system_run_start()["success"] is True
    pm._run_apply("tick", ready=False)
    assert (pm._run_state, pm._run_active.is_set()) == ("fault", False)


# --------------------------------------------------------------------------- #
# 10. Шаги pre_stop: охраняемый шаг исполняется в stopping и в проходе shutdown
# --------------------------------------------------------------------------- #


class _GuardedStepRouter(_StepRouter):
    """Шаг rig'а зовёт охраняемый обработчик плагина; снимок PM — в момент шага. ``late`` — посреди шага такт, START."""

    def __init__(self, rig: _Rig, plugin_rig: _PluginRig, *, late: bool) -> None:
        super().__init__(rig, hold=False)
        self.plugin_rig = plugin_rig
        self.late = late
        self.seen: list[dict[str, Any]] = []

    def request_async(self, message: dict, on_response: Callable, timeout: float = 5.0) -> str:
        pm = self.rig.pm
        obs: dict[str, Any] = {
            "state": pm._run_snapshot()[0].value,
            "stop_begun": pm._system_stop_snapshot() is not None,
            "flag": pm._run_active.is_set(),
            "run_event": pm._run_event.is_set(),
            "reply": self.plugin_rig.call(str(message["command"])),
        }
        if self.late:
            pm._run_apply("tick", ready=True)
            pm._run_apply("start", ready=True)
            obs["flag_after_late"] = pm._run_active.is_set()
            obs["state_after_late"] = pm._run_snapshot()[0].value
        self.seen.append(obs)
        return super().request_async(message, on_response, timeout)


def _step_rig(*, late: bool) -> tuple[_Rig, _GuardedStepRouter, _PluginRig]:
    rig = _Rig(("cam",), timeout_s=5.0, steps=True)
    rig.pm._pre_stop_steps = (PreStopStep(process="cam", command="robot_park_all", timeout_s=3.0),)
    plugin_rig = _PluginRig(ParkPlugin, ["robot_park_all"], rig.pm._run_active)
    router = _GuardedStepRouter(rig, plugin_rig, late=late)
    rig.router = router
    rig.pm.router_manager = router
    return rig, router, plugin_rig


@pytest.mark.timeout(60)
def test_operator_stop_step_runs_in_stopping() -> None:
    """STOP оператора из ``running``: шаг ``robot_park_all`` (заперт) идёт в ``stopping`` при снятом флаге и
    взведённом ``run_event`` — исполнен; итог ``ready``, флаг снят."""
    rig, router, plugin_rig = _step_rig(late=False)
    try:
        rig.to_running()
        assert rig.pm._run_active.is_set() is True
        assert plugin_rig.call("robot_park_all") == _REFUSAL, "в running шаг заперт"
        assert rig.stop() == {"success": True, "accepted": True, "state": "stopping"}
        assert _wait(lambda: len(router.seen) == 1, 3.0), "шаг pre_stop не начался"
        assert rig.wait_not_stopping(), "STOP не завершился"
        obs = router.seen[0]
        assert obs == {
            "state": "stopping",
            "stop_begun": False,
            "flag": False,
            "run_event": True,
            "reply": {"status": "ok", "parked": True},
        }, obs
        assert plugin_rig.plugin.park_calls == 1
        assert rig.state == "ready"
        assert rig.pm._run_active.is_set() is False
    finally:
        rig.close()


@pytest.mark.timeout(60)
def test_graceful_shutdown_from_running_step_runs_late_tick_start_keep_flag_clear() -> None:
    """Graceful ``system.shutdown`` из ``running`` (``run_gate`` true, шаг есть): во время шага состояние ``running``,
    ход стопа начат, флаг снят, ``run_event`` взведён, шаг исполнен (счётчик 1). Посреди шага поздние такт и START
    (прошли проверку стопа до его начала) флаг не взводят. После прохода — ``shutting_down``, флаг снят."""
    rig, router, plugin_rig = _step_rig(late=True)
    try:
        rig.to_running()
        assert rig.pm._run_active.is_set() is True
        reply = _bounded(lambda: rig.pm._cmd_system_shutdown({"mode": "graceful"}), _DEADLINE_S)
        assert reply.get("accepted") is True, reply
        assert _wait(lambda: rig.pm._system_stop_event.is_set(), _DEADLINE_S), (
            f"события останова не взведены: {rig.log}"
        )
        assert len(router.seen) == 1, router.seen
        assert router.seen[0] == {
            "state": "running",
            "stop_begun": True,
            "flag": False,
            "run_event": True,
            "reply": {"status": "ok", "parked": True},
            "flag_after_late": False,
            "state_after_late": "running",
        }, router.seen[0]
        assert plugin_rig.plugin.park_calls == 1
        assert rig.state == "shutting_down"
        assert rig.pm._run_active.is_set() is False
    finally:
        rig.close()


# --------------------------------------------------------------------------- #
# 11. Любой путь начала системного стопа снимает флаг сразу (единая точка — _begin_system_stop)
# --------------------------------------------------------------------------- #


def _running_pm() -> Any:
    pm = make_run_pm(True)
    assert pm._cmd_system_run_start()["success"] is True
    assert pm._run_active.is_set() is True
    return pm


def _stop_view(pm: Any) -> tuple[str, tuple[str, str] | None, bool]:
    snap = pm._system_stop_snapshot()
    begun = None if snap is None else (snap["mode"], snap["initiator"])
    return pm._run_state.value, begun, pm._run_active.is_set()


@pytest.mark.timeout(60)
def test_stop_begun_by_status_observer_clears_flag() -> None:
    """Путь «событие стопа взведено снаружи»: ``supervision.status`` начинает стоп сам (инициатор ``event``) — машина
    остаётся ``running``, флаг снят сразу после ответа (до правки — взведён, пока не придёт ``_run_apply``)."""
    pm = _running_pm()
    external = threading.Event()
    external.set()
    pm._system_stop_event = external
    _bounded(lambda: pm._cmd_supervision_status({}), _DEADLINE_S)
    assert _stop_view(pm) == ("running", ("graceful", "event"), False)


@pytest.mark.timeout(60)
def test_stop_begun_by_children_stop_clears_flag() -> None:
    """Путь стопа детей корня (``_ChildrenStop.request_stop``, событие стопа PM): ход стопа ``event`` начат, машина
    ``running``, флаг снят."""
    pm = _running_pm()
    _bounded(_ChildrenStop(pm).request_stop, _DEADLINE_S)
    assert _stop_view(pm) == ("running", ("graceful", "event"), False)


class _HeldPreStopExecutor:
    """Двойник исполнителя ``pm-pre-stop``, ещё не взявшего проход: ``submit`` только запоминает."""

    def __init__(self) -> None:
        self.held: list[tuple[Callable[[], Any], Callable[[Any], None]]] = []

    def submit(self, action: Callable[[], Any], key: Any, reply: Callable[[Any], None]) -> bool:
        self.held.append((action, reply))
        return True


@pytest.mark.timeout(60)
def test_graceful_shutdown_clears_flag_before_pass_starts() -> None:
    """Graceful ``system.shutdown`` из ``running`` с шагами: исполнитель шагов ещё не взял проход — флаг уже снят
    (ход стопа ``pre_stop`` начат, машина ``running``); после прохода — ``shutting_down``, флаг снят."""
    rig = _Rig(("cam",), timeout_s=5.0, steps=True)
    held = _HeldPreStopExecutor()
    rig.pm._pre_stop_executor = held
    try:
        rig.to_running()
        assert rig.pm._run_active.is_set() is True
        reply = _bounded(lambda: rig.pm._cmd_system_shutdown({"mode": "graceful"}), _DEADLINE_S)
        assert reply.get("accepted") is True, reply
        assert len(held.held) == 1
        assert _stop_view(rig.pm) == ("running", ("graceful", "unknown"), False)
        action, finish = held.held.pop(0)
        _bounded(lambda: finish(action()), _DEADLINE_S)
        assert (rig.state, rig.pm._run_active.is_set()) == ("shutting_down", False)
    finally:
        rig.close()


class _StopOrderSpy:
    """Обёртка над ``RunFlag`` PM: на ``clear()`` пишет ``(состояние, ход стопа уже виден, _run_lock занят)``."""

    def __init__(self, pm: Any, inner: RunFlag) -> None:
        self._pm = pm
        self._inner = inner
        self.log: list[tuple[str, bool, bool]] = []

    def set(self) -> None:
        self._inner.set()

    def clear(self) -> None:
        pm = self._pm
        self.log.append((pm._run_state.value, pm._system_stop_info is not None, pm._run_lock.locked()))
        self._inner.clear()

    def is_set(self) -> bool:
        return self._inner.is_set()


@pytest.mark.timeout(60)
def test_begin_system_stop_clears_flag_under_run_lock_before_stop_visible() -> None:
    """Начало стопа: флаг снимается под ``_run_lock`` ДО того, как ход стопа виден (как состояние в ``_run_apply``
    не опережает флаг); повтор начала (стоп уже идёт) флаг не трогает."""
    pm = _running_pm()
    spy = _StopOrderSpy(pm, pm._run_active)
    pm._run_active = spy
    assert _bounded(lambda: pm._begin_system_stop("graceful", "event", None), _DEADLINE_S) is True
    assert _bounded(lambda: pm._begin_system_stop("graceful", "event", None), _DEADLINE_S) is False
    assert spy.log == [("running", False, True)], spy.log
    assert spy.is_set() is False


# --------------------------------------------------------------------------- #
# 12. M1: негодный run_locked_commands закрывает — причина config, узел не готов, START отказан
# --------------------------------------------------------------------------- #

_PARK_CONFIG_REASON = {
    "node": "hazard_node.park",
    "severity": "failure",
    "reason": "park: неверный run_locked_commands",
    "source": "config",
}


def _start_with_child_readiness(snap: dict) -> tuple[str, dict]:
    """Снимок готовности узла -> heartbeat ребёнка ``cam`` в настоящий монитор PM -> такт -> START."""
    rig = _Rig(("cam",))
    try:
        rig.sim.set("cam", ready=snap["ready"], reasons=snap["reasons"])
        rig.sim.beat_now()
        rig.tick()
        state = rig.state
        return state, _bounded(rig.pm._cmd_system_run_start, _DEADLINE_S)
    finally:
        rig.close()


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "bad",
    ["robot_park_all", [1], ["robot_park_all", "no_such_command"]],
    ids=["string", "list_of_int", "unknown_name"],
)
def test_invalid_run_locked_key_gives_config_reason_and_refuses_start(bad: Any) -> None:
    """Негодный ключ: ERROR в журнале остаётся; снимок готовности узла — ровно одна причина ``failure``
    ``source: "config"`` «park: неверный run_locked_commands», ``ready`` ложно; PM по такому heartbeat —
    ``not_ready``, START отказан ``not_ready``."""
    plugin_rig = _PluginRig(ParkPlugin, bad, RunFlag())
    errors = [str(rec["msg"]) for rec in plugin_rig.orch._services.logs if rec["level"] == "ERROR"]
    assert len(errors) == 1 and "run_locked_commands" in errors[0], errors
    snap = plugin_rig.orch.readiness_snapshot(announced=True)
    assert [r for r in snap["reasons"] if r["source"] == "config"] == [_PARK_CONFIG_REASON], snap["reasons"]
    assert snap["ready"] is False
    state, reply = _start_with_child_readiness(snap)
    assert state == "not_ready"
    assert (reply["success"], reply["error"]) == (False, "not_ready"), reply


@pytest.mark.timeout(60)
def test_valid_run_locked_key_no_config_reason_start_accepted() -> None:
    """Годный ключ (контроль): причины config нет, узел готов, START принят."""
    plugin_rig = _PluginRig(ParkPlugin, ["robot_park_all"], RunFlag())
    snap = plugin_rig.orch.readiness_snapshot(announced=True)
    assert snap["reasons"] == [] and snap["ready"] is True, snap
    state, reply = _start_with_child_readiness(snap)
    assert state == "ready"
    assert reply == {"success": True, "state": "running"}, reply
