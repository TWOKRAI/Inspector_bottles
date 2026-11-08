# -*- coding: utf-8 -*-
"""Task 1.2a (gui-graceful-close) — слепая приёмка: ``system_stop`` в ``supervision.status`` и фаза стопа в сторе.

Написано ДО реализации по критериям приёмки брифа; DESIGN и реализация нового поведения не читались.

Критерии (что пинуется):
  A. ``supervision.status`` получает верхнее поле ``system_stop``: ``None``, пока системный стоп не начат; иначе
     словарь ``phase / mode / initiator / started_at / deadline_at / pre_stop_step``. Поля на процесс не меняются.
  B. ``system.shutdown``: ``initiator`` — имя отправителя внешнего ``process.command`` (иначе ``"unknown"``);
     ``phase`` на старте ``children``; ошибка аргументов стоп не начинает; первый стоп выигрывает.
  C. ``deadline_at``: graceful — ``started_at + pm_graceful_s``; force — момент команды + ``deadline_s``;
     force поверх graceful — ``mode``/``deadline_at`` обновляются, ``started_at``/``initiator`` сохраняются.
  D. Внешнее событие без команды — ``initiator == "event"``, ``mode == "graceful"``; ``supervision.status`` видит стоп
     уже при взведённом событии, до ``request_stop``.
  E. ``_ChildrenStop.request_stop`` объявляет фазу ``children`` ДО остановки исполнителя и паузы монитора.
  F. ``done``: после ``join_until == True``; иначе при закрытии области детей; НЕ позже остановки
     ``message_processor`` и закрытия ``state_store``; повторный force после ``done`` ничего не меняет.
  G. Стор: ``system.stop.{phase,mode,initiator,started_at}`` через ``handle_state_set`` (source ``ProcessManager``);
     графический graceful-стоп даёт РОВНО 5 дельт и 5 вызовов; сбой стора и его отсутствие стоп не ломают.

Два стенда:
  * «лёгкий» — PM через ``__new__`` (образец ``test_system_shutdown_force.py``) + настоящий ``_ChildrenStop`` + двойники
    группы/монитора/исполнителя/стора. Команда зовётся напрямую (отправителя нет => ``"unknown"``);
  * «живой» — ``Rig`` из ``test_pm_responsive_during_children_stop.py`` (настоящие ``GenericProcessManagerApp``,
    ``SharedResourcesManager``, ``StateStoreManager``/``TreeStore``, ``ProcessRegistry.children_stop``); команды —
    настоящий конверт ``process.command`` (``build_system_command_message``) в ``_handle_process_command``.
Дельты стора считаются по ответу настоящего ``handle_state_set`` (``changed``), а не по числу вызовов шпиона.
Ожидаемые значения — литералы. Всё, что может блокироваться, идёт в daemon-потоке с дедлайном join.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest

from multiprocess_framework.modules.message_module.builders.command_envelopes import build_system_command_message

from ..core.stop_budget import stop_budget
from ..process.process_manager_process import ProcessManagerProcess, _ChildrenStop
from .test_pm_responsive_during_children_stop import Rig

_CALL_DEADLINE_S = 10.0
_HOLD_S = 4.0  # «держащий» ребёнок: окно стопа открыто достаточно долго для проверок статуса
_CLOCK_TOL_S = 0.01

_STOP_KEYS = {"phase", "mode", "initiator", "started_at", "deadline_at", "pre_stop_step"}
_PROCESS_KEYS = {
    "incarnation",
    "restart_count",
    "last_exit",
    "status",
    "pid",
    "alive",
    "started_at",
    "instance_restarts",
    "stop_outcome",
    "stop_wave",
    "stop_deadline_at",
}


# --------------------------------------------------------------------------- #
# Общее
# --------------------------------------------------------------------------- #


def _bounded(fn: Callable[[], Any], deadline_s: float = _CALL_DEADLINE_S) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True, name="bounded-call")
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _status(pm: ProcessManagerProcess) -> dict:
    res = _bounded(pm._cmd_supervision_status)
    assert isinstance(res, dict) and res.get("success") is True, res
    return res


def _stop_info(pm: ProcessManagerProcess) -> dict | None:
    """Значение ``system_stop`` ответа ``supervision.status``; отсутствие ключа — провал по поведению."""
    res = _status(pm)
    assert "system_stop" in res, f"в ответе supervision.status нет ключа system_stop: ключи {sorted(res)}"
    return res["system_stop"]


def _assert_in_window(value: Any, lo: float, hi: float, what: str) -> None:
    assert isinstance(value, float), f"{what}: ожидался float (time.time()), получено {value!r}"
    assert lo - _CLOCK_TOL_S <= value <= hi + _CLOCK_TOL_S, f"{what}: {value:.4f} вне окна [{lo:.4f}, {hi:.4f}]"


# --------------------------------------------------------------------------- #
# Лёгкий стенд (PM через __new__)
# --------------------------------------------------------------------------- #


@dataclass
class _Write:
    path: str
    value: Any
    source: Any
    changed: bool


class _StoreSpy:
    """Двойник ``state_store_manager``: помнит значения и отвечает как настоящий (``changed`` только на смене)."""

    def __init__(self, journal: list[str], *, fail: bool = False) -> None:
        self._journal = journal
        self._fail = fail
        self._values: dict[str, Any] = {}
        self.calls = 0
        self.writes: list[_Write] = []

    def handle_state_set(self, msg: dict, *args: Any, **kwargs: Any) -> dict:
        self.calls += 1
        if self._fail:
            raise RuntimeError("store down")
        data = msg["data"] if isinstance(msg.get("data"), dict) else msg
        path = data.get("path")
        value = data.get("value")
        changed = path not in self._values or self._values[path] != value
        self._values[path] = value
        if isinstance(path, str) and path.startswith("system.stop."):
            self.writes.append(_Write(path, value, data.get("source"), changed))
            self._journal.append(f"store:{path}={value}")
        return {"status": "ok", "path": path, "changed": changed}

    def stop_writes(self) -> dict[str, Any]:
        return {w.path: w.value for w in self.writes}


class _Group:
    """Группа детей: ``join_until`` отдаёт заданный результат, ``result()`` — заданный итог."""

    def __init__(self, journal: list[str], *, join_result: bool, result: dict[str, bool]) -> None:
        self._journal = journal
        self.join_result = join_result
        self._result = result
        self.request_stop_calls = 0

    def request_stop(self) -> None:
        self.request_stop_calls += 1
        self._journal.append("group.request_stop")

    def join_until(self, deadline: float) -> bool:
        self._journal.append("group.join_until")
        return self.join_result

    def kill(self) -> None:
        self._journal.append("group.kill")

    def close(self) -> None:
        self._journal.append("group.close")

    def result(self) -> dict[str, bool]:
        return dict(self._result)


class _Monitor:
    def __init__(self, journal: list[str]) -> None:
        self._journal = journal

    def stop(self, *args: Any, **kwargs: Any) -> None:
        self._journal.append("monitor.stop")

    def get_supervision_snapshot(self) -> dict:
        return {}


class _Executor:
    def __init__(self, journal: list[str]) -> None:
        self._journal = journal

    def request_stop(self) -> None:
        self._journal.append("executor.request_stop")

    def join_until(self, deadline: float) -> bool:
        self._journal.append("executor.join_until")
        return True


class _Light:
    """PM (через ``__new__``) + настоящий ``_ChildrenStop`` + двойники группы, монитора, исполнителя и стора."""

    def __init__(
        self,
        *,
        join_result: bool = True,
        group_result: dict[str, bool] | None = None,
        store_fail: bool = False,
        store: bool = True,
    ) -> None:
        self.journal: list[str] = []
        self.group = _Group(self.journal, join_result=join_result, result=group_result or {})
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
        pm.name = "ProcessManager"
        pm.shared_resources = None
        pm.config = {}
        pm._process_monitor = _Monitor(self.journal)
        pm._lifecycle_executor = _Executor(self.journal)
        pm._process_registry = MagicMock()
        pm._process_registry.children_stop = MagicMock(return_value=self.group)
        for log in ("_log_info", "_log_warning", "_log_error", "_log_debug"):
            setattr(pm, log, MagicMock())
        self.store = _StoreSpy(self.journal, fail=store_fail)
        pm._state_store_manager = self.store if store else None
        pm.stop_event = threading.Event()
        pm._system_stop_event = threading.Event()
        self.pm = pm
        self.cs = _ChildrenStop(pm)
        pm._children_stop = self.cs

    def shutdown(self, data: dict | None = None) -> dict:
        """``system.shutdown`` напрямую (мимо конверта ``process.command``) в daemon-потоке с дедлайном."""
        return _bounded(lambda: self.pm._cmd_system_shutdown(data))

    def info(self) -> dict | None:
        return _stop_info(self.pm)

    @property
    def events_set(self) -> tuple[bool, bool]:
        return self.pm.stop_event.is_set(), self.pm._system_stop_event.is_set()


@pytest.fixture
def light() -> _Light:
    return _Light()


# --------------------------------------------------------------------------- #
# Живой стенд (Rig 1.1a)
# --------------------------------------------------------------------------- #


@pytest.fixture
def make_rig():
    rigs: list[Rig] = []

    def factory(graceful_s: float = 5.0) -> Rig:
        rig = Rig(graceful_s)
        rigs.append(rig)
        rig.start()
        return rig

    try:
        yield factory
    finally:
        for rig in rigs:
            rig.close()


def _gui_msg(data: dict | None = None, *, sender: str | None = "gui") -> dict:
    """Внешнее ``process.command``-сообщение ``system.shutdown`` (форма ``build_system_command_message``)."""
    msg = build_system_command_message({"cmd": "system.shutdown", **(data or {})}, sender=sender or "x")
    if sender is None:
        msg.pop("sender")
    return msg


def _send(rig: Rig, data: dict | None = None, *, sender: str | None = "gui") -> None:
    msg = _gui_msg(data, sender=sender)
    _bounded(lambda: rig.pm._handle_process_command(msg))


def _open_window(rig: Rig, data: dict | None = None, *, sender: str | None = "gui") -> tuple[Any, float, float]:
    """«Держащий» ребёнок + ``system.shutdown`` из ``process.command``; ждём сигнал стопа ребёнку.

    Возвращает ``(ребёнок, t_до, t_после)`` (``time.time()`` вокруг обработки команды). Предусловие — стоп
    действительно начался (ребёнок получил сигнал) и окно ещё открыто: без него красный тест был бы красным по стенду.
    """
    child = rig.add_child("hold", mode="slow", exit_after_s=_HOLD_S)
    t_before = time.time()
    _send(rig, data, sender=sender)
    t_after = time.time()
    assert rig.wait_until(lambda: child.t_stop_signal is not None, 15.0), "ребёнок не получил сигнал стопа"
    assert child.is_alive(), "предусловие: ребёнок уже мёртв — окно стопа не воспроизведено"
    return child, t_before, t_after


def _spy_store(rig: Rig) -> list[_Write]:
    """Журнал записей ``system.stop.*`` через НАСТОЯЩИЙ ``handle_state_set`` (дельта == ``changed`` в его ответе).

    Момент вызова ``phase=done`` попадает в ``rig.journal`` как ``store.done`` — до делегирования настоящему стору.
    """
    ssm = rig.pm._state_store_manager
    real = ssm.handle_state_set
    log: list[_Write] = []

    def spy(msg: dict, *args: Any, **kwargs: Any) -> Any:
        data = msg["data"] if isinstance(msg.get("data"), dict) else msg
        path = data.get("path")
        watched = isinstance(path, str) and path.startswith("system.stop.")
        if watched and path == "system.stop.phase" and data.get("value") == "done":
            rig.journal.append("store.done")
        result = real(msg, *args, **kwargs)
        if watched:
            changed = isinstance(result, dict) and result.get("changed") is True
            log.append(_Write(path, data.get("value"), data.get("source"), changed))
        return result

    ssm.handle_state_set = spy
    return log


# --------------------------------------------------------------------------- #
# S1. Нет стопа => system_stop: null
# --------------------------------------------------------------------------- #


def _status_of_bare_pm() -> ProcessManagerProcess:
    """PM как в ``test_process_manager_process.py``: ``__new__`` без ``__init__``, только поля supervision."""
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm._routing_epoch = 3
    pm._incarnations = {"camera": 2}
    mon = MagicMock()
    mon.get_supervision_snapshot.return_value = {"camera": {"status": "running", "last_exit": None, "restart_count": 1}}
    pm._process_monitor = mon
    return pm


@pytest.mark.timeout(90)
@pytest.mark.parametrize("stand", ["bare-new-pm", "light-rig", "live-rig"])
def test_no_stop_gives_null(stand: str, request: pytest.FixtureRequest) -> None:
    """Пока системный стоп не начат, ``system_stop`` есть в ответе и равен ``None`` (на любом стенде)."""
    if stand == "bare-new-pm":
        pm = _status_of_bare_pm()
    elif stand == "light-rig":
        pm = _Light().pm
    else:
        pm = request.getfixturevalue("make_rig")(5.0).pm
    res = _status(pm)
    assert "system_stop" in res, f"в ответе supervision.status нет ключа system_stop: ключи {sorted(res)}"
    assert res["system_stop"] is None, res["system_stop"]


def test_per_process_fields_unchanged_by_system_stop_field() -> None:
    """СТРАЖ (зелёный до и после): набор полей на процесс прежний — поле стопа верхнеуровневое, не процессное."""
    res = _status(_status_of_bare_pm())
    assert set(res["processes"]["camera"]) == _PROCESS_KEYS, sorted(res["processes"]["camera"])
    assert res["epoch"] == 3


# --------------------------------------------------------------------------- #
# S2. initiator из отправителя process.command; B: аргументы и «первый выигрывает»
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
@pytest.mark.parametrize("sender", ["gui", "backend_ctl"])
def test_shutdown_command_records_initiator_from_real_sender(make_rig, sender: str) -> None:
    """``initiator`` == имя отправителя внешнего ``process.command`` (GUI ``gui``, backend_ctl ``backend_ctl``)."""
    rig = make_rig(5.0)
    _open_window(rig, sender=sender)
    info = _stop_info(rig.pm)
    assert info is not None, "после system.shutdown supervision.status отдаёт system_stop=None"
    assert info["initiator"] == sender, info


@pytest.mark.timeout(90)
@pytest.mark.parametrize("route", ["envelope-without-sender", "direct-send-command", "direct-method-call"])
def test_no_sender_or_direct_command_gives_unknown(make_rig, route: str) -> None:
    """Без отправителя и при прямом ``send_command`` мимо конверта ``process.command`` — ``initiator == "unknown"``."""
    rig = make_rig(5.0)
    if route == "envelope-without-sender":
        _open_window(rig, sender=None)
    elif route == "direct-send-command":
        # Как в Rig 1.1a: прямое сообщение ``system.shutdown`` в системную очередь PM, sender="Probe" — НЕ инициатор.
        child = rig.add_child("hold", mode="slow", exit_after_s=_HOLD_S)
        rig.send("system.shutdown")
        assert rig.wait_until(lambda: child.t_stop_signal is not None, 15.0), "ребёнок не получил сигнал стопа"
        assert child.is_alive(), "предусловие: окно стопа не воспроизведено"
    else:
        rig.add_child("hold", mode="slow", exit_after_s=_HOLD_S)
        reply = _bounded(lambda: rig.pm._cmd_system_shutdown({}))
        assert reply.get("success") is True, reply
    info = _stop_info(rig.pm)
    assert info is not None, "после system.shutdown supervision.status отдаёт system_stop=None"
    assert info["initiator"] == "unknown", info


@pytest.mark.timeout(90)
def test_second_graceful_during_stop_changes_nothing(make_rig) -> None:
    """«Первый выигрывает»: повторный graceful не меняет mode/initiator/started_at/deadline_at."""
    rig = make_rig(5.0)
    _open_window(rig, sender="gui")
    first = _stop_info(rig.pm)
    assert first is not None, "после system.shutdown supervision.status отдаёт system_stop=None"
    assert first["initiator"] == "gui", first

    _send(rig, sender="backend_ctl")
    second = _stop_info(rig.pm)
    assert second == first, f"повторный graceful изменил system_stop: было {first}, стало {second}"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param({"mode": "x"}, id="mode-x"),
        pytest.param({"mode": "force", "deadline_s": 0.05}, id="deadline-0.05"),
        pytest.param({"mode": "force", "deadline_s": 5.1}, id="deadline-5.1"),
    ],
)
def test_bad_args_do_not_start_stop(light: _Light, data: dict) -> None:
    """Ошибка аргументов: ответ с ``error``, стоп НЕ начат — ``system_stop`` остаётся ``None``."""
    reply = light.shutdown(data)
    assert "error" in reply, reply
    assert light.events_set == (False, False)
    assert light.info() is None, "ошибка аргументов начала стоп: system_stop не None"
    assert light.store.writes == [], light.store.writes


def test_stop_state_fields_at_start(light: _Light) -> None:
    """Старт командой: ровно шесть ключей, ``phase == "children"``, ``mode == "graceful"``, время ``time.time()``."""
    t_before = time.time()
    reply = light.shutdown(None)
    t_after = time.time()
    assert reply.get("success") is True, reply
    info = light.info()
    assert info is not None, "после system.shutdown supervision.status отдаёт system_stop=None"
    assert set(info) == _STOP_KEYS, sorted(info)
    assert info["phase"] == "children", info
    assert info["mode"] == "graceful", info
    assert info["initiator"] == "unknown", info
    assert info["pre_stop_step"] is None, info
    _assert_in_window(info["started_at"], t_before, t_after, "started_at")


# --------------------------------------------------------------------------- #
# S3. Внешнее событие без команды
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("when", ["before-request-stop", "after-request-stop"])
def test_event_only_stop_reports_initiator_event(light: _Light, when: str) -> None:
    """Стоп без команды (событие взведено снаружи): ``initiator == "event"``, ``mode == "graceful"``.

    ``before-request-stop``: ``request_stop`` не звали, событие взведено (``_pm_stopping()``) — статус уже не ``None``.
    ``after-request-stop``: фаза 1 области детей отработала — фаза объявлена САМОЙ областью (до запроса статуса).
    """
    t_event = time.time()
    light.pm._system_stop_event.set()
    if when == "after-request-stop":
        _bounded(light.cs.request_stop)
        t_done = time.time()
        # Ещё НИ ОДНОГО запроса статуса: стор уже обязан знать об инициаторе (объявляет request_stop, а не статус).
        written = light.store.stop_writes()
        assert written.get("system.stop.initiator") == "event", light.store.writes
        assert written.get("system.stop.phase") == "children", light.store.writes
    else:
        assert light.group.request_stop_calls == 0, "предусловие: request_stop уже звали"
        t_done = time.time()
    info = light.info()
    assert info is not None, "событие стопа взведено, а supervision.status отдаёт system_stop=None"
    assert info["initiator"] == "event", info
    assert info["mode"] == "graceful", info
    assert info["phase"] == "children", info
    _assert_in_window(info["started_at"], t_event, max(t_done, time.time()), "started_at")


# --------------------------------------------------------------------------- #
# S4. deadline_at
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("data", "budget_s", "expected_s"),
    [
        pytest.param(None, None, 5.0, id="graceful-default-budget"),
        pytest.param({"mode": "graceful"}, 8.0, 8.0, id="graceful-budget-8"),
        pytest.param({"mode": "graceful", "deadline_s": 0.5}, None, 5.0, id="graceful-ignores-deadline_s"),
        pytest.param({"mode": "force", "deadline_s": 0.5}, None, 0.5, id="force-0.5"),
        pytest.param({"mode": "force", "deadline_s": 3.0}, 8.0, 3.0, id="force-3.0-budget-8"),
        pytest.param({"mode": "force", "deadline_s": 0.1}, None, 0.1, id="force-lower-bound"),
        pytest.param({"mode": "force", "deadline_s": 5.0}, None, 5.0, id="force-upper-bound"),
        pytest.param({"mode": "force"}, None, 1.0, id="force-default-deadline_s"),
    ],
)
def test_deadline_at_graceful_and_force(
    light: _Light, data: dict | None, budget_s: float | None, expected_s: float
) -> None:
    """graceful: ``started_at + pm_graceful_s`` бюджета PM; force: момент команды + ``deadline_s`` (умолч. 1.0)."""
    if budget_s is not None:
        light.pm._stop_budget = stop_budget(budget_s)
    t_before = time.time()
    reply = light.shutdown(data)
    t_after = time.time()
    assert reply.get("success") is True, reply
    info = light.info()
    assert info is not None, "после system.shutdown supervision.status отдаёт system_stop=None"
    _assert_in_window(info["deadline_at"], t_before + expected_s, t_after + expected_s, "deadline_at")
    if data is None or data.get("mode") != "force":
        assert info["deadline_at"] == pytest.approx(info["started_at"] + expected_s, abs=1e-6), info


# --------------------------------------------------------------------------- #
# S5. force поверх graceful
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_force_escalates_mode_and_deadline_keeps_started_and_initiator(make_rig) -> None:
    """force во время graceful: mode -> force, ``deadline_at`` = момент force + d; started_at/initiator прежние."""
    rig = make_rig(5.0)
    _open_window(rig, sender="gui")
    first = _stop_info(rig.pm)
    assert first is not None, "после system.shutdown supervision.status отдаёт system_stop=None"
    assert first["mode"] == "graceful", first

    t_before = time.time()
    _send(rig, {"mode": "force", "deadline_s": 0.5}, sender="backend_ctl")
    t_after = time.time()
    second = _stop_info(rig.pm)
    assert second is not None
    assert second["mode"] == "force", second
    _assert_in_window(second["deadline_at"], t_before + 0.5, t_after + 0.5, "deadline_at после force")
    assert second["started_at"] == first["started_at"], (first, second)
    assert second["initiator"] == "gui", second
    assert second["phase"] == "children", second


# --------------------------------------------------------------------------- #
# S6. Стор: ровно пять дельт
# --------------------------------------------------------------------------- #


def _await_closed(rig: Rig) -> None:
    assert rig.wait_root_closed(60.0), "корень PM не закрылся за дедлайн"


@pytest.mark.timeout(120)
def test_state_store_gets_five_deltas_for_graceful_stop(make_rig) -> None:
    """Графический graceful-стоп: 5 вызовов ``handle_state_set`` и РОВНО 5 дельт стора (4 при старте + done)."""
    rig = make_rig(5.0)
    log = _spy_store(rig)
    rig.add_child("quick", mode="slow", exit_after_s=0.3)
    t_before = time.time()
    _send(rig, sender="gui")
    t_after = time.time()
    _await_closed(rig)

    assert len(log) == 5, [(w.path, w.value, w.changed) for w in log]
    assert sum(w.changed for w in log) == 5, [(w.path, w.value, w.changed) for w in log]
    assert {w.source for w in log} == {"ProcessManager"}, [w.source for w in log]
    start, done = log[:4], log[4]
    started = {w.path: w.value for w in start}
    assert set(started) == {
        "system.stop.phase",
        "system.stop.mode",
        "system.stop.initiator",
        "system.stop.started_at",
    }, [w.path for w in start]
    assert started["system.stop.phase"] == "children"
    assert started["system.stop.mode"] == "graceful"
    assert started["system.stop.initiator"] == "gui"
    _assert_in_window(started["system.stop.started_at"], t_before, t_after, "system.stop.started_at")
    assert (done.path, done.value) == ("system.stop.phase", "done"), done


@pytest.mark.timeout(90)
def test_force_over_graceful_adds_one_mode_delta(make_rig) -> None:
    """force поверх graceful добавляет ещё одну запись ``mode`` (6 вызовов и 6 дельт, пока стоп идёт)."""
    rig = make_rig(5.0)
    log = _spy_store(rig)
    _open_window(rig, sender="gui")
    assert len(log) == 4, [(w.path, w.value) for w in log]
    _send(rig, {"mode": "force", "deadline_s": 0.5}, sender="backend_ctl")
    assert len(log) == 5, [(w.path, w.value) for w in log]
    assert (log[4].path, log[4].value, log[4].changed) == ("system.stop.mode", "force", True), log[4]


@pytest.mark.parametrize("store", ["raises", "none"])
def test_store_failure_or_missing_store_does_not_break_shutdown(store: str) -> None:
    """Сбой ``handle_state_set`` и ``state_store_manager is None`` не ломают ``system.shutdown``."""
    light = _Light(store_fail=(store == "raises"), store=(store != "none"))
    reply = light.shutdown(None)
    assert reply.get("success") is True, reply
    assert "error" not in reply, reply
    assert light.events_set == (True, True)
    if store == "raises":
        assert light.store.calls >= 1, "стоп не пытался писать в стор — сбой не был проверен"
    info = light.info()
    assert info is not None, "стор недоступен, и supervision.status потерял стоп: system_stop=None"
    assert info["phase"] == "children", info


# --------------------------------------------------------------------------- #
# S7. Фаза children объявлена первой
# --------------------------------------------------------------------------- #


def test_phase_children_announced_before_lifecycle_executor_stops(light: _Light) -> None:
    """``request_stop``: запись ``phase=children`` в стор раньше остановки исполнителя и паузы монитора."""
    _bounded(light.cs.request_stop)
    journal = list(light.journal)
    assert "store:system.stop.phase=children" in journal, journal
    assert "executor.request_stop" in journal and "monitor.stop" in journal, journal
    announced = journal.index("store:system.stop.phase=children")
    assert announced < journal.index("executor.request_stop"), journal
    assert announced < journal.index("monitor.stop"), journal


# --------------------------------------------------------------------------- #
# S8. done
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("child_mode", "graceful_s"),
    [pytest.param("slow", 5.0, id="child-exits-in-time"), pytest.param("terminate", 1.0, id="child-needs-terminate")],
)
def test_done_phase_set_before_message_processor_and_state_store_close(
    make_rig, child_mode: str, graceful_s: float
) -> None:
    """``phase=done`` виден в сторе ПОСЛЕ смерти детей и ДО ``workers.stop_all`` и закрытия ``state_store``."""
    rig = make_rig(graceful_s)
    log = _spy_store(rig)
    rig.add_child("kid", mode=child_mode, exit_after_s=0.3)
    _send(rig, sender="gui")
    _await_closed(rig)

    journal = list(rig.journal)
    assert "store.done" in journal, (
        f"phase=done не записан в стор вовсе: {journal}; записи {[(w.path, w.value) for w in log]}"
    )
    done = journal.index("store.done")
    assert "child.dead" in journal and "workers.stop_all" in journal and "state_store" in journal, journal
    assert journal.index("child.dead") < done, f"done раньше смерти детей: {journal}"
    assert done < journal.index("workers.stop_all"), f"done позже остановки message_processor: {journal}"
    assert done < journal.index("state_store"), f"done позже закрытия state_store: {journal}"


def test_force_after_done_changes_nothing_and_publishes_nothing(light: _Light) -> None:
    """После ``done`` повторный force не меняет ``mode`` и не пишет в стор."""
    assert light.shutdown(None).get("success") is True
    _bounded(light.cs.request_stop)
    assert _bounded(lambda: light.cs.join_until(time.monotonic() + 5.0)) is True
    before = light.info()
    assert before is not None and before["phase"] == "done", before
    writes_before = len(light.store.writes)

    reply = light.shutdown({"mode": "force", "deadline_s": 0.5})
    assert reply.get("success") is True, reply
    after = light.info()
    assert after is not None
    assert after["mode"] == "graceful", after
    assert after["deadline_at"] == before["deadline_at"], (before, after)
    assert len(light.store.writes) == writes_before, light.store.writes[writes_before:]


def test_close_with_survivors_sets_done() -> None:
    """Выжившие (``join_until`` -> False, ``result()`` с False): ``done`` только при закрытии области детей."""
    survivors = _Light(join_result=False, group_result={"stuck": False})
    assert survivors.shutdown(None).get("success") is True
    _bounded(survivors.cs.request_stop)
    assert _bounded(lambda: survivors.cs.join_until(time.monotonic() + 5.0)) is False
    _bounded(survivors.cs.kill)
    assert _bounded(lambda: survivors.cs.join_until(time.monotonic() + 5.0)) is False
    mid = survivors.info()
    # 1.2a r2: join_until после kill() — последний ход области до закрытия message_processor, done ставится здесь.
    assert mid is not None and mid["phase"] == "done", f"done не выставлен после kill и join_until: {mid}"

    _bounded(survivors.cs.close)
    final = survivors.info()
    assert final is not None and final["phase"] == "done", final
    assert survivors.store.stop_writes().get("system.stop.phase") == "done", survivors.store.writes
