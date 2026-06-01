"""Тесты ModbusDevice — state machine, телеметрия, callbacks, ошибки."""

from __future__ import annotations

import pytest

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.core.status import ConnectionState
from Services.modbus.sdk.errors import ModbusIOError

from .conftest import FakeClock, FakeSdkClient


# --- соединение ---


def test_connect_sets_connected(device: ModbusDevice) -> None:
    assert device.connect() is True
    assert device.state is ConnectionState.CONNECTED
    assert device.is_connected


def test_connect_failure_sets_error(config: ModbusConfig) -> None:
    fake = FakeSdkClient()
    fake.fail_connect = True
    dev = ModbusDevice(config, client=fake)
    assert dev.connect() is False
    assert dev.state is ConnectionState.ERROR
    assert "connect failed" in dev.get_status()["last_error"]


def test_disconnect_resets_state(device: ModbusDevice) -> None:
    device.connect()
    device.disconnect()
    assert device.state is ConnectionState.DISCONNECTED
    assert device.get_status()["connected_since"] is None


# --- чтение/запись + телеметрия ---


def test_read_holding_returns_values(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    fake_client.holding = {0: 11, 1: 22, 2: 33}
    device.connect()
    assert device.read_holding(0, 3) == [11, 22, 33]
    assert device.get_status()["reads_ok"] == 1


def test_write_register_persists(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    device.connect()
    assert device.write_register(5, 99) is True
    assert fake_client.holding[5] == 99
    assert device.get_status()["writes_ok"] == 1


def test_write_registers_block(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    device.connect()
    device.write_registers(0, [1, 2, 3])
    assert fake_client.holding == {0: 1, 1: 2, 2: 3}


def test_read_error_increments_counter_and_raises(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    device.connect()
    fake_client.fail_next_op = True
    with pytest.raises(ModbusIOError):
        device.read_holding(0, 1)
    status = device.get_status()
    assert status["reads_err"] == 1
    assert status["state"] == "error"


def test_write_error_increments_counter(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    device.connect()
    fake_client.fail_next_op = True
    with pytest.raises(ModbusIOError):
        device.write_register(0, 1)
    assert device.get_status()["writes_err"] == 1


# --- callbacks ---


def test_on_status_called_on_connect(config: ModbusConfig, fake_client: FakeSdkClient) -> None:
    states: list[str] = []
    dev = ModbusDevice(config, client=fake_client, on_status=lambda s: states.append(s["state"]))
    dev.connect()
    assert "connecting" in states
    assert "connected" in states


def test_on_error_called_on_failure(config: ModbusConfig) -> None:
    fake = FakeSdkClient()
    fake.fail_connect = True
    errors: list[str] = []
    dev = ModbusDevice(config, client=fake, on_error=errors.append)
    dev.connect()
    assert errors and "connect failed" in errors[0]


def test_on_data_called_on_read(device_with_data) -> None:
    dev, payloads = device_with_data
    dev.connect()
    dev.read_holding(0, 2)
    assert payloads and payloads[-1]["op"] == "read_holding"


def test_uptime_reported(config: ModbusConfig, fake_client: FakeSdkClient) -> None:
    clock = FakeClock()
    dev = ModbusDevice(config, client=fake_client, clock=clock)
    dev.connect()
    clock.t = 12.0
    assert dev.get_status()["uptime_sec"] == 12.0


# --- локальная фикстура для on_data ---


@pytest.fixture
def device_with_data(config: ModbusConfig, fake_client: FakeSdkClient):
    payloads: list[dict] = []
    dev = ModbusDevice(config, client=fake_client, on_data=payloads.append)
    return dev, payloads
