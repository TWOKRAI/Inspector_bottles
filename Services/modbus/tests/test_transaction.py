"""Тесты ModbusDevice.transaction — атомарная серия записей (контракт RegisterTransport).

Ключевые инварианты:
- операции выполняются строго по порядку под одним Lock;
- abort на ПЕРВОЙ ошибке: оставшиеся операции (включая маркер-флаг) не выполняются;
- ModbusDevice структурно реализует RegisterTransport.
"""

from __future__ import annotations

import pytest

from Services.modbus.core.device import ModbusDevice
from Services.modbus.interfaces import RegisterTransport
from Services.modbus.sdk.errors import ModbusIOError

from .conftest import FakeSdkClient


def test_transaction_executes_ops_in_order(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    device.connect()
    ok = device.transaction(
        [
            ("w", 0x1101, 1505),
            ("w", 0x1102, 63533),
            ("wm", 0x1104, [0xD687, 0x0012]),
            ("w", 0x1100, 1),  # маркер — последним
        ]
    )
    assert ok is True
    write_calls = [(op, args) for op, args in fake_client.calls if op.startswith("write")]
    assert write_calls == [
        ("write_register", (0x1101, 1505)),
        ("write_register", (0x1102, 63533)),
        ("write_registers", (0x1104, [0xD687, 0x0012])),
        ("write_register", (0x1100, 1)),
    ]
    assert fake_client.holding[0x1100] == 1


def test_transaction_aborts_on_first_error(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    """Маркер 0x1100 НЕ должен записаться, если упала запись данных."""
    device.connect()
    fake_client.holding[0x1100] = 0
    fake_client.fail_next_op = True  # упадёт первая же запись
    with pytest.raises(ModbusIOError):
        device.transaction(
            [
                ("w", 0x1101, 123),
                ("w", 0x1100, 1),  # маркер
            ]
        )
    assert 0x1101 not in fake_client.holding  # данные не легли
    assert fake_client.holding[0x1100] == 0  # маркер не взведён
    status = device.get_status()
    assert status["writes_err"] == 1
    assert status["state"] == "error"


def test_transaction_mid_series_abort(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    """Ошибка в середине серии: выполненное до неё остаётся, после — нет."""
    device.connect()
    device.transaction([("w", 0x10, 1)])  # прогрев: одна успешная серия
    fake_client.calls.clear()

    # Первая операция пройдёт, вторая упадёт, третья (маркер) не должна выполниться
    original_write = fake_client.write_register
    state = {"n": 0}

    def flaky_write(address: int, value: int) -> None:
        state["n"] += 1
        if state["n"] == 2:
            raise ModbusIOError("fake: mid-series failure")
        original_write(address, value)

    fake_client.write_register = flaky_write  # type: ignore[method-assign]
    with pytest.raises(ModbusIOError):
        device.transaction(
            [
                ("w", 0x20, 11),
                ("w", 0x21, 22),
                ("w", 0x22, 1),  # маркер
            ]
        )
    assert fake_client.holding.get(0x20) == 11
    assert 0x21 not in fake_client.holding
    assert 0x22 not in fake_client.holding


def test_transaction_rejects_unknown_op(device: ModbusDevice) -> None:
    device.connect()
    with pytest.raises(ValueError, match="неизвестная операция"):
        device.transaction([("x", 0, 1)])


def test_transaction_counts_writes(device: ModbusDevice) -> None:
    device.connect()
    device.transaction([("w", 0, 1), ("wm", 1, [2, 3])])
    assert device.get_status()["writes_ok"] == 2


def test_transaction_emits_on_data(config, fake_client) -> None:
    payloads: list[dict] = []
    dev = ModbusDevice(config, client=fake_client, on_data=payloads.append)
    dev.connect()
    dev.transaction([("w", 0, 1)])
    assert payloads[-1] == {"op": "transaction", "count": 1}


def test_device_satisfies_register_transport(device: ModbusDevice) -> None:
    """ModbusDevice структурно реализует RegisterTransport (Protocol)."""
    assert isinstance(device, RegisterTransport)


def test_read_registers_alias(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    fake_client.holding = {7: 42}
    device.connect()
    assert device.read_registers(7) == [42]
    assert device.read_registers(7, 2) == [42, 0]
