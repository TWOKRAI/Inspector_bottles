"""Слепые приёмочные тесты 2.2a2 S4a: ``DeviceManager.pause_all`` и способность драйвера ``pause_action``.

Контракт (литералы брифа): ``PAUSE_OPS == frozenset({"stop", "abort"})``; атрибут класса ``pause_action``
(``tuple[str, dict] | None``); ``pause_all(deadline, skip=frozenset())`` — абсолютный срок
``time.monotonic()``, по одному
результату на запись реестра, ключ — id устройства; переопределение записи ``params["pause_action"] = {"op", "args"}``.

Новые имена импортируются ВНУТРИ тестов: каждый тест красен на базе сам по себе. Всё, что может зависнуть, идёт в
daemon-потоке со сроком ожидания; ожидание — опрос со сроком. Ожидаемые значения — литералы, не из тестируемого кода.
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from Services.device_hub.drivers.base import BaseDeviceDriver
from Services.device_hub.manager import DeviceManager
from Services.device_hub.spi import OpSpec

KIND = "pausedev"
JOIN_S = 8.0  # срок ожидания потока pause_all, с (с запасом поверх любого сценария ниже)
MGR_LOGGER = "Services.device_hub.manager"

OK_STOP = {"status": "ok", "op": "stop"}
SOFT = ("stop", {"level": "SOFT"})


# --------------------------------------------------------------------------- #
# Двойники и стенд
# --------------------------------------------------------------------------- #


class _Dev(BaseDeviceDriver):
    """Двойник драйвера: пишет вызовы ``call`` (op, args, момент), длится ``call_s``, отвечает ``reply``/бросает."""

    kind = KIND
    pause_action = None
    call_s = 0.0
    reply: dict | None = None
    raises: BaseException | None = None

    def __init__(self, entry: Any) -> None:
        super().__init__(entry)
        self.log: list[tuple[str, dict, float]] = []
        self.finished = 0  # сколько вызовов ``call`` вернулись/упали
        self.active = 0  # сколько вызовов ``call`` идёт сейчас
        self.guard = threading.Lock()
        self.linked = False

    @property
    def is_connected(self) -> bool:
        return self.linked

    def connect(self) -> bool:
        self.linked = True
        return True

    def disconnect(self) -> None:
        self.linked = False

    def tick(self, stop_event: Any = None) -> dict | None:
        return None

    def call(self, op: str, args: dict) -> dict:
        with self.guard:
            self.log.append((op, dict(args), time.monotonic()))
            self.active += 1
        try:
            if self.call_s:
                time.sleep(self.call_s)
            if self.raises is not None:
                raise self.raises
            return dict(self.reply) if self.reply is not None else {"status": "ok"}
        finally:
            with self.guard:
                self.active -= 1
                self.finished += 1

    def sent(self) -> list[tuple[str, dict]]:
        with self.guard:
            return [(op, args) for op, args, _t in self.log]

    def first_at(self) -> float:
        with self.guard:
            return self.log[0][2]


def _double(pause_action: tuple[str, dict] | None, **attrs: Any) -> type[_Dev]:
    """Подкласс двойника с классовой способностью ``pause_action`` и заданными атрибутами."""
    return type("Double", (_Dev,), {"pause_action": pause_action, **attrs})


class _Plain:
    """Драйвер НЕ ``BaseDeviceDriver`` и без ``pause_action`` (RED 1)."""

    def __init__(self, entry: Any) -> None:
        self.linked = False

    @property
    def is_connected(self) -> bool:
        return self.linked

    def connect(self) -> bool:
        self.linked = True
        return True

    def disconnect(self) -> None:
        self.linked = False

    def call(self, op: str, args: dict) -> dict:
        return {"status": "ok"}


class _Rig:
    """``DeviceManager`` на настоящей области ``open_scope``; драйверы — из фабрик теста, записи — через ``upsert``."""

    def __init__(self) -> None:
        self.scope = open_scope("t", budget_s=5.0, reporter=None)
        self.mgr = DeviceManager(store=None, spawn=self.scope.spawn)
        self.makers: dict[str, Callable[[Any], Any]] = {}
        self.mgr.register_driver_factory(KIND, lambda entry, proto: self.makers[entry.id](entry))
        assert self.mgr.initialize() is True

    def add(self, dev_id: str, maker: Callable[[Any], Any], *, params: dict | None = None, connect: bool = True) -> Any:
        self.makers[dev_id] = maker
        self.mgr.upsert({"id": dev_id, "name": dev_id, "kind": KIND, "params": params or {}})
        if connect:
            assert self.mgr.connect(dev_id) is True
        return self.mgr.get_driver(dev_id)

    def drain(self, timeout_s: float = 8.0) -> None:
        """Дождаться, пока все вызовы ``call`` двойников вернутся (опрос со сроком)."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            drivers = [self.mgr.get_driver(e.id) for e in self.mgr.snapshot_registry()]
            if all(getattr(d, "active", 0) == 0 for d in drivers):
                return
            time.sleep(0.02)

    def close(self) -> None:
        self.drain()
        self.scope.close()


@pytest.fixture
def rig() -> Iterator[_Rig]:
    r = _Rig()
    try:
        yield r
    finally:
        r.close()


class _Run:
    """Результат одного ``pause_all`` в daemon-потоке: ``done``, ``res``, ``err``, ``t_start``, ``t_end``."""

    def __init__(self) -> None:
        self.res: dict | None = None
        self.err: BaseException | None = None
        self.t_start = 0.0
        self.t_end = 0.0
        self.done = False

    @property
    def elapsed(self) -> float:
        return self.t_end - self.t_start


def _pause(mgr: DeviceManager, deadline: float, skip: frozenset[str] | None = None, join_s: float = JOIN_S) -> _Run:
    run = _Run()

    def body() -> None:
        run.t_start = time.monotonic()
        try:
            run.res = mgr.pause_all(deadline) if skip is None else mgr.pause_all(deadline, skip=skip)
        except BaseException as exc:  # noqa: BLE001 - тест сам разбирает ошибку
            run.err = exc
        run.t_end = time.monotonic()

    th = threading.Thread(target=body, daemon=True, name="pause_all_call")
    th.start()
    th.join(join_s)
    run.done = not th.is_alive()
    return run


def _ok(run: _Run) -> dict:
    """Результат ``pause_all`` без зависания и без исключения (иначе красный с причиной)."""
    assert run.done, "pause_all завис"
    assert run.err is None, repr(run.err)
    assert run.res is not None
    return run.res


def _wait(predicate: Callable[[], bool], timeout_s: float) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _wait_until(moment: float) -> None:
    """Дойти до момента ``moment`` (``time.monotonic()``) опросом."""
    while time.monotonic() < moment:
        time.sleep(0.01)


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.warnings: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno == logging.WARNING:
            self.warnings.append(record.getMessage())


@pytest.fixture
def mgr_warnings() -> Iterator[_Records]:
    """Все WARNING логгера ``Services.device_hub.manager`` (обработчик прямо на логгере: не зависит от propagate)."""
    handler = _Records()
    log = logging.getLogger(MGR_LOGGER)
    log.addHandler(handler)
    try:
        yield handler
    finally:
        log.removeHandler(handler)


# --------------------------------------------------------------------------- #
# 1. Способности и драйвер без pause_action
# --------------------------------------------------------------------------- #


def test_pause_ops_literal() -> None:
    """1: ``PAUSE_OPS`` — ровно ``frozenset({"stop", "abort"})``."""
    from Services.device_hub.drivers.base import PAUSE_OPS

    assert PAUSE_OPS == frozenset({"stop", "abort"})


def test_base_driver_has_no_pause_action_by_default() -> None:
    """1: умолчание ``BaseDeviceDriver.pause_action is None``."""
    assert BaseDeviceDriver.pause_action is None


@pytest.mark.parametrize(
    ("module", "cls_name", "expected"),
    [
        ("Services.device_hub.drivers.robot_driver_v2", "RobotDriverV2", ("stop", {"level": "SOFT"})),
        ("Services.device_hub.drivers.robot_driver", "RobotDriver", ("abort", {"mode": 3})),
        ("Services.device_hub.drivers.vfd_driver", "VfdDriver", ("stop", {})),
        ("Services.device_hub.drivers.hikvision_driver", "HikvisionDriver", None),
        ("Services.device_hub.drivers.generic_modbus_driver", "GenericModbusDriver", None),
    ],
    ids=["RobotDriverV2", "RobotDriver", "VfdDriver", "HikvisionDriver", "GenericModbusDriver"],
)
def test_driver_class_pause_action(module: str, cls_name: str, expected: tuple[str, dict] | None) -> None:
    """1: ``pause_action`` каждого штатного драйвера — литерал брифа (читается с класса, без экземпляров)."""
    cls = getattr(importlib.import_module(module), cls_name)
    assert cls.pause_action == expected


def test_plain_object_driver_is_skipped_no_pause_action(rig: _Rig) -> None:
    """1: драйвер не ``BaseDeviceDriver`` и без ``pause_action`` -> skipped/no_pause_action, без исключения."""
    rig.add("x1", _Plain)
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert res == {"x1": {"status": "skipped", "reason": "no_pause_action"}}


# --------------------------------------------------------------------------- #
# 2. Параллельность
# --------------------------------------------------------------------------- #


def _robot_then_belt(rig: _Rig) -> tuple[Any, Any]:
    robot = rig.add("robot", _double(SOFT, call_s=1.0))  # робот зарегистрирован РАНЬШЕ ремня
    belt = rig.add("belt", _double(("stop", {})))
    return robot, belt


def test_parallel_belt_gets_stop_while_robot_command_runs(rig: _Rig) -> None:
    """2: ремень получает ``stop`` не позже 0.3 с от начала вызова, хотя команда робота идёт 1.0 с."""
    _robot, belt = _robot_then_belt(rig)
    run = _pause(rig.mgr, time.monotonic() + 1.5)
    _ok(run)
    assert belt.sent() == [("stop", {})]
    assert belt.first_at() - run.t_start <= 0.3


def test_parallel_returns_within_robot_time_and_both_ok(rig: _Rig) -> None:
    """2: ``pause_all`` возвращается не позже 1.3 с; оба результата ``{"status": "ok", "op": "stop"}``."""
    _robot_then_belt(rig)
    run = _pause(rig.mgr, time.monotonic() + 1.5)
    res = _ok(run)
    assert run.elapsed <= 1.3
    assert res == {"robot": OK_STOP, "belt": OK_STOP}


# --------------------------------------------------------------------------- #
# 3. Литералы результатов
# --------------------------------------------------------------------------- #


def test_result_ok_literal_and_command_sent(rig: _Rig) -> None:
    """3: успех -> ``{"status": "ok", "op": "stop"}`` и драйвер получил ``stop`` с аргументами способности."""
    dev = rig.add("d1", _double(SOFT))
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert res == {"d1": OK_STOP}
    assert dev.sent() == [("stop", {"level": "SOFT"})]


def test_result_never_connected_is_skipped_not_connected(rig: _Rig) -> None:
    """3: запись есть, ни разу не подключена -> ``skipped``/``not_connected``."""
    rig.add("d1", _double(SOFT), connect=False)
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert res == {"d1": {"status": "skipped", "reason": "not_connected"}}


def test_result_disconnected_after_connect_is_skipped_not_connected(rig: _Rig) -> None:
    """3: подключено, затем ``disconnect`` -> ``skipped``/``not_connected``, команды нет."""
    dev = rig.add("d1", _double(SOFT))
    rig.mgr.disconnect("d1")
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert res == {"d1": {"status": "skipped", "reason": "not_connected"}}
    assert dev.sent() == []


def test_result_skip_set_is_already_stopped_without_command(rig: _Rig) -> None:
    """3: id в ``skip`` -> ``skipped``/``already_stopped`` и ни одной команды; сосед получает свою."""
    robot = rig.add("robot", _double(SOFT))
    belt = rig.add("belt", _double(("stop", {})))
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5, skip=frozenset({"robot"})))
    assert res == {"robot": {"status": "skipped", "reason": "already_stopped"}, "belt": OK_STOP}
    assert robot.sent() == []
    assert belt.sent() == [("stop", {})]


def test_result_class_without_pause_action_is_skipped_without_command(rig: _Rig) -> None:
    """3: класс с ``pause_action = None`` -> ``skipped``/``no_pause_action``, команды нет."""
    dev = rig.add("d1", _double(None))
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert res == {"d1": {"status": "skipped", "reason": "no_pause_action"}}
    assert dev.sent() == []


@pytest.mark.parametrize(
    "attrs",
    [{"reply": {"status": "error"}}, {"raises": RuntimeError("сбой связи")}],
    ids=["error_reply", "raising_call"],
)
def test_result_failing_device_is_error_with_text_and_neighbour_still_stopped(rig: _Rig, attrs: dict) -> None:
    """3: ответ error / исключение ``call`` -> ``error``, ``op == "stop"``, ``message`` — str; сосед получил стоп."""
    rig.add("bad", _double(SOFT, **attrs))
    good = rig.add("good", _double(("stop", {})))
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert res["bad"]["status"] == "error"
    assert res["bad"]["op"] == "stop"
    assert isinstance(res["bad"]["message"], str)
    assert good.sent() == [("stop", {})]
    assert res["good"] == OK_STOP


# --------------------------------------------------------------------------- #
# 4. Переопределение params["pause_action"]
# --------------------------------------------------------------------------- #

_OPS = (
    OpSpec(name="stop", immediate=True),
    OpSpec(name="abort", immediate=True),
    OpSpec(name="park", immediate=True),
    OpSpec(name="enqueue_job"),
)


def _override_double() -> type[_Dev]:
    return _double(SOFT, OP_SPECS=_OPS)


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"op": "stop", "args": {"level": "HALT"}}, ("stop", {"level": "HALT"})),
        ({"op": "abort", "args": {"mode": 3}}, ("abort", {"mode": 3})),
    ],
    ids=["stop_halt", "abort_mode3"],
)
def test_override_valid_replaces_class_action(rig: _Rig, override: dict, expected: tuple[str, dict]) -> None:
    """4: допустимое переопределение (``stop``/``abort``, ``immediate`` в ``OP_SPECS``) заменяет способность класса."""
    dev = rig.add("d1", _override_double(), params={"pause_action": override})
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert dev.sent() == [expected]
    assert res == {"d1": {"status": "ok", "op": expected[0]}}


@pytest.mark.parametrize(
    "override",
    [{"op": "fly"}, {"op": "park"}, {"op": "enqueue_job"}],
    ids=["unknown_op", "immediate_but_not_pause_op", "not_immediate"],
)
def test_override_invalid_falls_back_to_class_action_with_one_warning(
    rig: _Rig, mgr_warnings: _Records, override: dict
) -> None:
    """4: недопустимая операция -> ``stop SOFT`` и ровно один WARNING на значение, даже за два ``pause_all``."""
    dev = rig.add("d1", _override_double(), params={"pause_action": override})
    first = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    second = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert first == {"d1": OK_STOP}
    assert second == {"d1": OK_STOP}
    assert dev.sent() == [("stop", {"level": "SOFT"}), ("stop", {"level": "SOFT"})]
    assert len(mgr_warnings.warnings) == 1, mgr_warnings.warnings


# --------------------------------------------------------------------------- #
# 5. Срок и команда «в полёте»
# --------------------------------------------------------------------------- #

NO_REPLY = {"status": "error", "op": "stop", "message": "нет ответа к сроку"}
STILL_RUNNING = {"status": "error", "op": "stop", "message": "предыдущий стоп ещё идёт"}


def _slow(rig: _Rig) -> Any:
    return rig.add("slow", _double(SOFT, call_s=3.0))


def test_deadline_no_reply_returns_in_time_with_literal(rig: _Rig) -> None:
    """5: команда 3.0 с, срок +1.5 с -> возврат не позже 1.7 с с ``нет ответа к сроку``; команда ушла одна."""
    slow = _slow(rig)
    run = _pause(rig.mgr, time.monotonic() + 1.5)
    res = _ok(run)
    assert run.elapsed <= 1.7
    assert res == {"slow": NO_REPLY}
    assert slow.sent() == [("stop", {"level": "SOFT"})]


def test_repeat_while_in_flight_is_refused_without_second_command(rig: _Rig) -> None:
    """5: повтор на 2.0 с, пока первая команда ещё идёт -> ``предыдущий стоп ещё идёт``, всего команд 1."""
    slow = _slow(rig)
    t0 = time.monotonic()
    _ok(_pause(rig.mgr, t0 + 1.5))
    _wait_until(t0 + 2.0)
    res = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert res == {"slow": STILL_RUNNING}
    assert len(slow.sent()) == 1


def test_after_late_thread_exit_next_call_sends_again(rig: _Rig) -> None:
    """5: после выхода позднего потока (>= 3.3 с) третий вызов шлёт команду снова — всего 2."""
    slow = _slow(rig)
    t0 = time.monotonic()
    _ok(_pause(rig.mgr, t0 + 1.5))
    _wait_until(t0 + 3.3)
    assert _wait(lambda: slow.finished == 1, 2.0), "первая команда не завершилась"
    third = _ok(_pause(rig.mgr, time.monotonic() + 1.5))
    assert len(slow.sent()) == 2
    assert third == {"slow": NO_REPLY}


def test_returned_dict_is_not_rewritten_by_late_reply(rig: _Rig) -> None:
    """5: словарь первого вызова не меняется, когда запоздавший ответ всё же пришёл (>= 3.3 с)."""
    slow = _slow(rig)
    t0 = time.monotonic()
    res = _ok(_pause(rig.mgr, t0 + 1.5))
    assert res == {"slow": NO_REPLY}
    _wait_until(t0 + 3.3)
    assert _wait(lambda: slow.finished == 1, 2.0), "первая команда не завершилась"
    assert res == {"slow": NO_REPLY}
