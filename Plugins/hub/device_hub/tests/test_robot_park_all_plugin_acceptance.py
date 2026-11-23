"""Слепая приёмка T5.3e.5a (бриф 5t-a), плагин: команда ``robot_park_all`` на исполнителе, хук, роутер.

Purpose:
    Строки ``plans/robot-protocol-v2/tasks/T5.3e.5a.acceptance.md`` про команду плагина: регистрация на исполнителе
    ``device_io`` «для всех ключей», отказ без исполнителя, отказ после хука ``request_stop(ctx)``, отказ исполнителя
    ``system_stopping`` по пути роутера, один сквозной тест с настоящим драйвером v2. Обвязка — ``Rig`` / ``RouterPath``
    слепой приёмки SPI (настоящие ``CommandManager`` / ``ExecutorManager`` / ``RouterManager``). Логику менеджера
    проверяет ``Services/device_hub/tests/test_robot_park_all_acceptance.py``. Источник требований — файл приёмки,
    не код плагина.

Public API:
    Только тесты ``test_*``.

Stability: lite

Допущения теста (не из приёмки буквально):
    * «Для всех ключей» = метаданные команды в каталоге: ``executor == "device_io"``, ``targets == "all"``, ключа
      ``key_from`` нет (так каталог ``CommandManager`` показывает ``register_command(..., targets="all")``).
    * «Закрытие приёма исполнителем» = ``rig.em.get("device_io").request_stop()`` (фаза 1 остановки процесса).
    * «Вызов команды напрямую» = ``CommandManager.handle_command({...})`` без ``reply``: исполняется на месте.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.test_spi_commands_acceptance import FakeDriver, RouterPath, Rig, bounded
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, pulse
from Services.robot_comm.tests.e2e_rig_v2 import bounded as e2e_bounded

pytestmark = pytest.mark.timeout(90)

COMMAND = "robot_park_all"
TEXT_NO_EXECUTOR = "robot_park_all: нет исполнителя device_io"
TEXT_STOP_HUB = "идёт остановка хаба"
EXECUTORS = {"device_io": {}}
_CALL_S = 20.0
_CONNECT_S = 60.0

_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2parkallplg", budget_s=6.0)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


@pytest.fixture
def make_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Rig]]:
    rigs: list[Rig] = []

    def new(sub: str = "main", **kwargs: Any) -> Rig:
        path = tmp_path / sub
        path.mkdir(parents=True, exist_ok=True)
        rig = Rig(path, monkeypatch, **kwargs)
        rigs.append(rig)
        return rig

    yield new
    for rig in reversed(rigs):
        rig.close()


def _fake_v2_robot(rig: Rig, dev_id: str = "r1") -> FakeDriver:
    """Подключённый поддельный робот v2: его ``call`` пишется, любое обращение к роботу видно в ``calls``."""
    rig.factory("robot", lambda entry, proto: FakeDriver(entry, proto))
    rig.upsert(dev_id, "robot", "delta_v2")
    assert rig.connect(dev_id) is True
    return rig.driver(dev_id)


def _close_intake(rig: Rig) -> None:
    """Закрыть приём исполнителя ``device_io`` (фаза 1 остановки процесса): новые команды получают отказ."""
    executor = rig.em.get("device_io")
    assert executor is not None, "обвязка: исполнитель device_io не создан"
    executor.request_stop()


def _command(rig: Rig, data: dict | None = None) -> Any:
    return bounded(lambda: rig.cm.handle_command({"command": COMMAND, "data": dict(data or {})}), _CALL_S)


# --------------------------------------------------------------------------------------------------
# Регистрация и отказ без исполнителя
# --------------------------------------------------------------------------------------------------


def test_command_is_declared_by_the_plugin() -> None:
    """Команда ``robot_park_all`` входит в ``DeviceHubPlugin.commands``."""
    assert COMMAND in DeviceHubPlugin.commands


def test_registered_on_device_io_executor_for_all_keys(make_rig: Callable[..., Rig]) -> None:
    """В каталоге: ``executor "device_io"``, ``targets "all"`` («все ключи»), ``key_from`` нет."""
    rig = make_rig(executors=EXECUTORS)
    info = rig.cm.get_command_info(COMMAND)
    assert info is not None, "команда не зарегистрирована"
    metadata = info.get("metadata") or {}
    assert metadata.get("executor") == "device_io", metadata
    assert metadata.get("targets") == "all", metadata
    assert "key_from" not in metadata, metadata


def test_without_executor_refuses_with_literal_and_robots_untouched(make_rig: Callable[..., Rig]) -> None:
    """Без исполнителя в процессе: ``{"status": "error", "message": "robot_park_all: нет исполнителя device_io"}``."""
    rig = make_rig()  # секции executors нет
    robot = _fake_v2_robot(rig)
    assert _command(rig) == {"status": "error", "message": TEXT_NO_EXECUTOR}
    assert robot.calls.items == [], robot.calls.items


# --------------------------------------------------------------------------------------------------
# Хук и роутер
# --------------------------------------------------------------------------------------------------


def test_after_hook_command_called_directly_refuses_hub_stopping(make_rig: Callable[..., Rig]) -> None:
    """После ``plugin.request_stop(ctx)`` прямой вызов: ``{"status": "error", "message": "идёт остановка хаба"}``."""
    rig = make_rig(executors=EXECUTORS)
    robot = _fake_v2_robot(rig)
    bounded(lambda: rig.plugin.request_stop(rig.ctx), _CALL_S)
    assert _command(rig) == {"status": "error", "message": TEXT_STOP_HUB}
    assert robot.calls.items == [], robot.calls.items


def test_before_hook_command_is_not_refused_as_stopping(make_rig: Callable[..., Rig]) -> None:
    """Контроль хука: до ``request_stop`` отказа «идёт остановка хаба» нет (без роботов — ``ok``)."""
    rig = make_rig(executors=EXECUTORS)
    answer = _command(rig)
    assert answer.get("message") != TEXT_STOP_HUB, answer
    assert answer.get("status") == "ok", answer


def test_through_router_normal_path_replies_once_off_router_thread(make_rig: Callable[..., Rig]) -> None:
    """По пути роутера (приём открыт): один ответ вне потока роутера; без роботов — ``ok``, ``robots: {}``, 30.0."""
    rig = make_rig(executors=EXECUTORS)
    path = RouterPath(rig)
    path.request(COMMAND, {}, deadline_s=_CALL_S)
    time.sleep(0.2)  # лишний ответ, если он есть, успел бы прийти
    assert len(path.replies) == 1, path.replies
    result, reply_thread = path.replies[0]
    assert result["status"] == "ok" and result["timeout_s"] == 30.0 and result["robots"] == {}, result
    assert reply_thread != "router-thread", reply_thread


def test_control_closed_intake_refuses_any_executor_command_system_stopping(make_rig: Callable[..., Rig]) -> None:
    """Контроль обвязки (зелёный сейчас): после закрытия приёма даже ``robot_point_list`` -> ``system_stopping``."""
    rig = make_rig(executors=EXECUTORS)
    rig.upsert("r1", "robot", "delta_v2")
    _close_intake(rig)
    path = RouterPath(rig)
    path.request("robot_point_list", {"device_id": "r1"})
    assert path.replies[0][0] == {"success": False, "error": "system_stopping"}, path.replies


def test_through_router_after_intake_closed_executor_refuses_system_stopping(make_rig: Callable[..., Rig]) -> None:
    """После закрытия приёма исполнителем ответ команды — отказ исполнителя ``system_stopping``; роботы не тронуты."""
    rig = make_rig(executors=EXECUTORS)
    robot = _fake_v2_robot(rig)
    _close_intake(rig)
    path = RouterPath(rig)
    path.request(COMMAND, {}, deadline_s=_CALL_S)
    assert len(path.replies) == 1, path.replies
    assert path.replies[0][0] == {"success": False, "error": "system_stopping"}, path.replies
    assert robot.calls.items == [], robot.calls.items


# --------------------------------------------------------------------------------------------------
# Сквозной: настоящие объекты
# --------------------------------------------------------------------------------------------------


def test_end_to_end_real_driver_through_router_and_executor(make_rig: Callable[..., Rig]) -> None:
    """Плагин + исполнитель + роутер + настоящий драйвер v2 над sim: робот вне дома -> ``done``/``moved``."""
    rig = make_rig(executors=EXECUTORS)
    with E2eRig() as sim:
        clock = FakeClock()
        entry = DeviceEntry(
            id="r1",
            name="r1",
            kind="robot",
            protocol="delta_v2",
            transport={"type": "tcp", "host": "127.0.0.1", "port": sim.port, "unit_id": ROBOT_UNIT_ID},
        )
        drv = RobotDriverV2(entry, clock=clock.clock, sleep=clock.sleep, spawn=_SCOPE.spawn)
        rig.factory("robot", lambda _entry, _proto: drv)
        rig.upsert("r1", "robot", "delta_v2", transport=entry.transport)
        assert bounded(lambda: rig.plugin._manager.connect("r1"), _CONNECT_S) is True
        drv.desired_connected = True
        try:
            moved = e2e_bounded(lambda: drv.call("jog_step", {"dx": 80, "dy": 0, "spd": 50}), _CALL_S)
            assert moved["status"] == "ok", moved
            end = time.monotonic() + 10
            while not (abs(sim.pose_wire()[0] - 380.0) <= 0.05 and sim.read("TLM_MOVING") == [0]):
                assert time.monotonic() < end, "робот не встал в x == 380"
                time.sleep(0.02)
            path = RouterPath(rig)
            with pulse(drv.tick, 0.05):
                path.request(COMMAND, {}, deadline_s=_CALL_S)
            assert len(path.replies) == 1, path.replies
            result = path.replies[0][0]
            assert result["status"] == "ok", result
            robot = result["robots"]["r1"]
            assert (robot["result"], robot["seq"], robot["home"]) == ("done", 1, "moved"), robot
            assert abs(sim.pose_wire()[0] - 300.0) <= 0.5, sim.pose_wire()
        finally:
            try:
                e2e_bounded(drv.disconnect, _CALL_S)
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass
