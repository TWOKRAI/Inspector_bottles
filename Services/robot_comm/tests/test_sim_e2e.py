"""E2E-smoke: RobotClient -> TCP sim_robot (реальный pymodbus, локальный сокет).

Прогоняется только при установленной pymodbus; основной объём тестов идёт
против FakeRobotTransport без сети (test_client.py).
"""

from __future__ import annotations

import socket
import time

import pytest

from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig

pytestmark = pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def sim():
    from Services.robot_comm.server.sim_robot import SimRobotServer

    server = SimRobotServer("127.0.0.1", _free_port())
    server.start()
    time.sleep(0.5)  # дать серверу подняться
    yield server
    server.stop()


@pytest.fixture
def bot(sim) -> RobotClient:
    client = RobotClient(RobotConfig(host=sim.host, port=sim.port))
    assert client.connect()
    yield client
    client.disconnect()


def _wait(predicate, timeout: float = 3.0) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_position_and_telemetry(bot: RobotClient) -> None:
    t = bot.read_telemetry()
    assert t.spd_pct == 50  # дефолт sim-ядра
    assert bot.read_position() is not None


def test_encoder_runs(bot: RobotClient) -> None:
    first = bot.read_encoder()
    assert _wait(lambda: bot.read_encoder() > first)


def test_job_roundtrip_over_tcp(bot: RobotClient) -> None:
    assert _wait(bot.is_free)
    assert bot.send_job(75.0, -30.5, bot.read_encoder())
    assert _wait(bot.job_accepted)
    assert _wait(bot.is_free)
    echo = bot.read_echo()
    assert echo.job_x == pytest.approx(75.0)
    assert echo.job_y == pytest.approx(-30.5)


def test_vfd_mirror_over_bridge(bot: RobotClient) -> None:
    """Мост: запись mailbox ПЧ через транзакцию клиента -> sim зеркалит статус."""
    assert bot.transaction(
        [
            ("w", 0x1202, 5000),  # 50.00 Гц
            ("w", 0x1201, 0),
            ("w", 0x1200, 1),
            ("w", 0x1204, 1),  # VFD_FLAG — последним
        ]
    )
    assert _wait(lambda: bot.read_registers(0x1210, 2) == [1, 5000])
