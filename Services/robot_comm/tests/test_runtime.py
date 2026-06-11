"""Тесты runtime-holder — модель владельца соединения."""

from __future__ import annotations

import pytest

from Services.robot_comm import runtime
from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.errors import RobotNotConnectedError
from Services.robot_comm.testing.fake_transport import FakeRobotTransport


@pytest.fixture(autouse=True)
def _clean_runtime():
    runtime.clear()
    yield
    runtime.clear()


def _make_client() -> RobotClient:
    return RobotClient(RobotConfig(), transport=FakeRobotTransport())


def test_get_without_owner_raises_with_colocation_hint() -> None:
    with pytest.raises(RobotNotConnectedError, match="ОДНОМ process_name"):
        runtime.get_client()


def test_set_get_clear_cycle() -> None:
    client = _make_client()
    runtime.set_client(client)
    assert runtime.get_client() is client
    assert runtime.peek_client() is client
    runtime.clear()
    assert runtime.peek_client() is None


def test_second_owner_rejected() -> None:
    runtime.set_client(_make_client())
    with pytest.raises(RuntimeError, match="один владелец"):
        runtime.set_client(_make_client())


def test_clear_idempotent() -> None:
    runtime.clear()
    runtime.clear()
