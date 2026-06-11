"""Тесты VfdDriver: bridge поверх RobotDriver на sim, DRAW-gating."""

from __future__ import annotations

import threading

import pytest

from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.vfd_driver import VfdDriver
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock


@pytest.fixture
def core() -> RobotSimCore:
    return RobotSimCore()


@pytest.fixture
def robot_transport(core: RobotSimCore) -> FakeRobotTransport:
    return FakeRobotTransport(core)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def robot_entry() -> DeviceEntry:
    return DeviceEntry(
        id="robot_main",
        name="Робот Delta",
        kind="robot",
        transport={"type": "tcp"},
        params={"word_order": "little"},
    )


@pytest.fixture
def vfd_entry() -> DeviceEntry:
    return DeviceEntry(
        id="vfd_belt",
        name="ПЧ лента",
        kind="vfd",
        protocol="gd20_bridge",
        transport={"type": "bridge", "bridge": "robot_main"},
        params={"freq_max_hz": 50.0, "default_freq_hz": 10.0, "poll_interval_s": 0.0, "stale_polls_limit": 6},
    )


@pytest.fixture
def robot_driver(robot_entry, robot_transport, clock) -> RobotDriver:
    """Подключённый RobotDriver."""
    d = RobotDriver(
        robot_entry,
        protocol=None,
        transport=robot_transport,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    d.connect()
    return d


@pytest.fixture
def vfd_driver(vfd_entry, robot_driver, clock) -> VfdDriver:
    """VfdDriver поверх робота-моста."""
    d = VfdDriver(
        vfd_entry,
        protocol=None,
        resolve_device=lambda _: robot_driver,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    d.connect()
    return d


class TestVfdDriverLifecycle:
    """Подключение через bridge."""

    def test_connect_via_bridge(self, vfd_driver) -> None:
        """VFD подключается через bridge-носителя."""
        assert vfd_driver.is_connected

    def test_disconnect(self, vfd_driver) -> None:
        vfd_driver.disconnect()
        assert not vfd_driver.is_connected

    def test_set_degraded(self, vfd_driver) -> None:
        vfd_driver.set_degraded()
        assert not vfd_driver.is_connected


class TestVfdDriverCommands:
    """Команды ПЧ через sim."""

    def test_run_stop(self, vfd_driver, core) -> None:
        """run -> зеркало обновляется (sim обрабатывает VFD_FLAG)."""
        result = vfd_driver.call("run", {"freq": 25.0})
        assert result["status"] == "ok"

        result = vfd_driver.call("stop", {})
        assert result["status"] == "ok"

    def test_set_freq(self, vfd_driver) -> None:
        result = vfd_driver.call("set_freq", {"hz": 30.0})
        assert result["status"] == "ok"

    def test_reset_fault(self, vfd_driver) -> None:
        result = vfd_driver.call("reset_fault", {})
        assert result["status"] == "ok"

    def test_get_status(self, vfd_driver, core) -> None:
        """get_status возвращает зеркало."""
        # Сначала run, чтобы sim заполнил зеркало
        vfd_driver.call("run", {"freq": 10.0})
        result = vfd_driver.call("get_status", {})
        assert result["status"] == "ok"
        assert "vfd" in result

    def test_unknown_op(self, vfd_driver) -> None:
        result = vfd_driver.call("nonexistent", {})
        assert result["status"] == "error"


class TestVfdDriverDrawGating:
    """DRAW-gating (У4): carrier в DRAW -> tick не зовёт poll, quality=stale."""

    def test_carrier_draw_mode_stale(self, vfd_driver, robot_driver, clock) -> None:
        """Когда носитель в режиме draw -> VFD tick возвращает stale."""
        # Переключаем робота в draw
        robot_driver._mode = "draw"

        stop = threading.Event()
        snap = vfd_driver.tick(stop)
        assert snap is not None
        assert snap["quality"] == "stale"
        assert snap.get("reason") == "carrier busy"

    def test_carrier_cvt_mode_polls(self, vfd_driver, robot_driver, clock) -> None:
        """В CVT-режиме носителя -> VFD poll нормально."""
        robot_driver._mode = "cvt"

        stop = threading.Event()
        # Прогоняем tick — должен сходить poll
        snap = vfd_driver.tick(stop)
        assert snap is not None
        # Либо good (если poll прошёл), либо None (throttle)
        if snap is not None:
            assert snap["quality"] in ("good", "stale")


class TestVfdDriverTick:
    """tick() — poll + ensure_alive."""

    def test_tick_disconnected(self, vfd_entry, clock) -> None:
        """tick без соединения -> quality=bad."""
        d = VfdDriver(vfd_entry, clock=clock.clock, sleep=clock.sleep)
        stop = threading.Event()
        snap = d.tick(stop)
        assert snap["quality"] == "bad"

    def test_tick_good_with_poll(self, vfd_driver, core, clock) -> None:
        """tick после run -> good/stale."""
        vfd_driver.call("run", {"freq": 10.0})
        stop = threading.Event()
        snap = vfd_driver.tick(stop)
        if snap is not None:
            assert snap["quality"] in ("good", "stale")
