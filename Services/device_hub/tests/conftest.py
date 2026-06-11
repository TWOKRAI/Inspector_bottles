"""Фикстуры тестов device_hub."""

from __future__ import annotations

import pytest

from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

from Services.device_hub.registry.entry import DeviceEntry


class FakeClock:
    """Управляемые часы для детерминированных тестов."""

    def __init__(self) -> None:
        self.t = 0.0

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sim_core() -> RobotSimCore:
    return RobotSimCore()


@pytest.fixture
def fake_transport(sim_core: RobotSimCore) -> FakeRobotTransport:
    return FakeRobotTransport(sim_core)


@pytest.fixture
def robot_entry() -> DeviceEntry:
    """Запись реестра для робота (tcp)."""
    return DeviceEntry(
        id="robot_main",
        name="Робот Delta",
        kind="robot",
        protocol="delta_universal3",
        transport={"type": "tcp", "host": "192.168.1.7", "port": 502, "unit_id": 2},
        params={"word_order": "little", "feed_poll_s": 0.05, "telemetry_interval_s": 0.5},
    )


@pytest.fixture
def vfd_entry() -> DeviceEntry:
    """Запись реестра для ПЧ (bridge через robot_main)."""
    return DeviceEntry(
        id="vfd_belt",
        name="ПЧ лента",
        kind="vfd",
        protocol="gd20_bridge",
        transport={"type": "bridge", "bridge": "robot_main"},
        params={"freq_max_hz": 50.0, "default_freq_hz": 10.0, "poll_interval_s": 0.5, "stale_polls_limit": 6},
    )


@pytest.fixture
def generic_entry() -> DeviceEntry:
    """Запись реестра для generic_modbus устройства."""
    return DeviceEntry(
        id="sensor_1",
        name="Датчик давления",
        kind="generic_modbus",
        protocol="gd20_bridge",  # переиспользуем для теста
        transport={"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 1},
    )
