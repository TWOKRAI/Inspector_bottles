"""Фикстуры тестов robot_comm — клиент поверх FakeRobotTransport (без сети)."""

from __future__ import annotations

import pytest

from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport


class FakeClock:
    """Управляемые часы: каждый вызов sleep продвигает время — без реальных пауз."""

    def __init__(self) -> None:
        self.t = 0.0

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def core() -> RobotSimCore:
    return RobotSimCore()


@pytest.fixture
def transport(core: RobotSimCore) -> FakeRobotTransport:
    return FakeRobotTransport(core)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def bot(transport: FakeRobotTransport, clock: FakeClock) -> RobotClient:
    """Подключённый клиент поверх фейк-робота, время — детерминированное."""
    client = RobotClient(RobotConfig(), transport=transport, clock=clock.clock, sleep=clock.sleep)
    client.connect()
    return client
