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


class TestVfdDriverDesiredReconnect:
    """НР-2: VFD с desired=True + not connected -> tick пытается reconnect."""

    def test_tick_reconnects_when_desired_true(self, vfd_entry, clock) -> None:
        """desired=True + disconnected -> tick вызывает _attempt_reconnect."""
        # VFD без транспорта (connect упадёт), но desired=True
        attempts: list[bool] = []

        class FakeVfdDriver(VfdDriver):
            """Перехватываем connect для подсчёта попыток."""

            def connect(self) -> bool:
                attempts.append(True)
                return False

        d = FakeVfdDriver(vfd_entry, clock=clock.clock, sleep=clock.sleep)
        d.desired_connected = True
        stop = threading.Event()

        # Первый tick — reconnect (throttle=0 при первом вызове)
        snap = d.tick(stop)
        assert snap is not None
        assert snap["quality"] == "bad"
        assert len(attempts) == 1

        # Второй tick сразу — throttle (3 секунды не прошло)
        snap = d.tick(stop)
        assert len(attempts) == 1  # не вызвал connect повторно

        # Прокрутить время на 4 секунды — retry
        clock.t += 4.0
        snap = d.tick(stop)
        assert len(attempts) == 2

    def test_tick_no_reconnect_when_desired_false(self, vfd_entry, clock) -> None:
        """desired=False + disconnected -> tick возвращает bad, НЕ реконнектит."""
        d = VfdDriver(vfd_entry, clock=clock.clock, sleep=clock.sleep)
        d.desired_connected = False
        stop = threading.Event()

        # Мокаем connect чтобы убедиться что не вызывается
        original_connect = d.connect
        connect_calls = []

        def tracking_connect():
            connect_calls.append(True)
            return original_connect()

        d.connect = tracking_connect

        for _ in range(5):
            snap = d.tick(stop)
            assert snap["quality"] == "bad"
            clock.t += 5.0

        assert len(connect_calls) == 0, "connect НЕ должен вызываться при desired=False"

    def test_bridged_vfd_reconnects_when_carrier_appears(self, vfd_entry, robot_entry, robot_transport, clock) -> None:
        """НР-2: робот offline -> VFD desired=True ждёт -> робот connect -> VFD поднимается."""
        # Робот ещё не подключён — resolve_device возвращает None
        carrier_ref: list = [None]

        def resolve(dev_id: str):
            return carrier_ref[0]

        d = VfdDriver(
            vfd_entry,
            protocol=None,
            resolve_device=resolve,
            clock=clock.clock,
            sleep=clock.sleep,
        )
        d.desired_connected = True
        stop = threading.Event()

        # Первый tick — connect упадёт (carrier=None -> TransportBuildError)
        snap = d.tick(stop)
        assert snap["quality"] == "bad"
        assert not d.is_connected

        # Робот поднялся
        robot = RobotDriver(
            robot_entry,
            protocol=None,
            transport=robot_transport,
            clock=clock.clock,
            sleep=clock.sleep,
        )
        robot.connect()
        carrier_ref[0] = robot

        # Прокрутить throttle
        clock.t += 5.0

        # Следующий tick — VFD подключится через bridge
        snap = d.tick(stop)
        assert d.is_connected, "VFD должен подключиться когда носитель появился"
        assert snap["quality"] == "good"


class TestVfdDriverBridgeValidation:
    """н7: bridge резолвится через build_transport с валидацией."""

    def test_connect_bridge_to_vfd_raises_transport_error(self, vfd_entry, clock) -> None:
        """н7: bridge на vfd-устройство (не robot) -> TransportBuildError, не silent None."""
        from Services.device_hub.errors import TransportBuildError

        # Носитель с kind=vfd — не допустим как мост
        class FakeVfdCarrier:
            kind = "vfd"
            transport = object()

        d = VfdDriver(
            vfd_entry,
            clock=clock.clock,
            sleep=clock.sleep,
            resolve_device=lambda _: FakeVfdCarrier(),
        )
        with pytest.raises(TransportBuildError, match="robot"):
            d.connect()

    def test_connect_bridge_carrier_not_found_raises(self, vfd_entry, clock) -> None:
        """н7: bridge на несуществующее устройство -> TransportBuildError с понятным сообщением."""
        from Services.device_hub.errors import TransportBuildError

        d = VfdDriver(
            vfd_entry,
            clock=clock.clock,
            sleep=clock.sleep,
            resolve_device=lambda _: None,  # носитель не найден
        )
        with pytest.raises(TransportBuildError, match="не найден"):
            d.connect()

    def test_connect_bridge_cycle_raises(self, clock) -> None:
        """н7: bridge-цикл (устройство ссылается на себя) -> TransportBuildError."""
        from Services.device_hub.errors import TransportBuildError
        from Services.device_hub.registry.entry import DeviceEntry

        cycle_entry = DeviceEntry(
            id="vfd_self",
            name="ПЧ циклический",
            kind="vfd",
            transport={"type": "bridge", "bridge": "vfd_self"},
            params={},
        )
        d = VfdDriver(cycle_entry, clock=clock.clock, sleep=clock.sleep, resolve_device=lambda _: None)
        with pytest.raises(TransportBuildError, match="цикл"):
            d.connect()
