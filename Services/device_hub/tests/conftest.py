"""Фикстуры тестов device_hub."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from Services.robot_comm.core.client_v2 import RobotClientV2
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

from Services.device_hub.registry.entry import DeviceEntry


class ClientRecorder:
    """Шов SPI.f: ``client_factory`` драйвера робота v2 — строит НАСТОЯЩИЙ ``RobotClientV2`` и хранит ссылку.

    ``.last`` — последний созданный клиент, ``.all`` — все по порядку. Тест отдаёт рекордер драйверу
    (``client_factory=rec`` или ``DeviceManager.set_driver_options("robot", client_factory=rec)``) и читает клиента
    после ``connect``; ``drv._client`` не нужен. Зовётся из потока подключения, список растёт под замком.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[RobotClientV2] = []

    def __call__(self, transport: Any, cfg: Any) -> RobotClientV2:
        client = RobotClientV2(transport, cfg)
        with self._lock:
            self._clients.append(client)
        return client

    @property
    def last(self) -> RobotClientV2:
        with self._lock:
            assert self._clients, "клиент ещё не создан: connect драйвера не вызывался"
            return self._clients[-1]

    @property
    def all(self) -> list[RobotClientV2]:
        with self._lock:
            return list(self._clients)


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
