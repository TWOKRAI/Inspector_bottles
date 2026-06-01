"""Тесты ModbusPoller — опрос блоков и изоляция ошибок."""

from __future__ import annotations

from Services.modbus.core.device import ModbusDevice
from Services.modbus.core.poller import ModbusPoller, RegisterBlock, RegisterKind

from .conftest import FakeSdkClient


def test_register_block_kind_normalized() -> None:
    block = RegisterBlock(name="x", kind="holding", address=0)  # type: ignore[arg-type]
    assert block.kind is RegisterKind.HOLDING


def test_poll_once_reads_blocks(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    fake_client.holding = {0: 10, 1: 20}
    fake_client.inputs = {100: 7}
    device.connect()
    poller = ModbusPoller(
        device,
        [
            RegisterBlock("regs", RegisterKind.HOLDING, 0, 2),
            RegisterBlock("sensor", RegisterKind.INPUT, 100, 1),
        ],
    )
    result = poller.poll_once()
    assert result["regs"] == [10, 20]
    assert result["sensor"] == [7]


def test_poll_block_error_isolated(device: ModbusDevice, fake_client: FakeSdkClient) -> None:
    device.connect()
    fake_client.fail_next_op = True  # упадёт первый блок, второй прочитается
    fake_client.holding = {0: 5}
    poller = ModbusPoller(
        device,
        [
            RegisterBlock("first", RegisterKind.COILS, 0, 1),
            RegisterBlock("second", RegisterKind.HOLDING, 0, 1),
        ],
    )
    result = poller.poll_once()
    assert "error" in result["first"]
    assert result["second"] == [5]


def test_from_specs_builds_blocks(device: ModbusDevice) -> None:
    poller = ModbusPoller.from_specs(
        device,
        [{"name": "a", "kind": "holding", "address": 0, "count": 4}],
    )
    assert poller.blocks[0].count == 4
    assert poller.blocks[0].kind is RegisterKind.HOLDING
