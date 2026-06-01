"""Тесты ModbusChannel — драйвер как канал RouterManager (P4)."""

from __future__ import annotations

from multiprocess_framework.modules.router_module.channels.base_channel import MessageChannel

from Services.modbus.channels.modbus_channel import ModbusChannel
from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.core.poller import RegisterBlock, RegisterKind

from .conftest import FakeSdkClient


def _channel(blocks=None, *, connect=True):
    fake = FakeSdkClient()
    dev = ModbusDevice(ModbusConfig(unit_id=1), client=fake)
    if connect:
        dev.connect()
    ch = ModbusChannel("modbus_1", dev, poll_blocks=blocks, auto_connect=False)
    return ch, dev, fake


def test_is_message_channel() -> None:
    ch, _, _ = _channel()
    assert isinstance(ch, MessageChannel)
    assert ch.name == "modbus_1"
    assert ch.channel_type == "modbus"


# --- OUTBOUND send ---


def test_send_read() -> None:
    ch, _, fake = _channel()
    fake.holding = {0: 5, 1: 6}
    result = ch.send({"command": "modbus.read", "data": {"address": 0, "count": 2}})
    assert result["status"] == "success"
    assert result["values"] == [5, 6]


def test_send_write() -> None:
    ch, _, fake = _channel()
    result = ch.send({"command": "modbus.write", "data": {"address": 3, "value": 42}})
    assert result["status"] == "success"
    assert fake.holding[3] == 42


def test_send_write_many() -> None:
    ch, _, fake = _channel()
    ch.send({"command": "modbus.write_many", "data": {"address": 0, "values": [1, 2, 3]}})
    assert fake.holding == {0: 1, 1: 2, 2: 3}


def test_send_status() -> None:
    ch, _, _ = _channel()
    result = ch.send({"command": "modbus.status"})
    assert result["status"] == "success"
    assert result["state"] == "connected"


def test_send_unknown_command() -> None:
    ch, _, _ = _channel()
    result = ch.send({"command": "modbus.frobnicate"})
    assert result["status"] == "error"


def test_send_error_on_device_failure() -> None:
    ch, _, fake = _channel()
    fake.fail_next_op = True
    result = ch.send({"command": "modbus.write", "data": {"address": 0, "value": 1}})
    assert result["status"] == "error"
    assert "reason" in result


# --- INBOUND poll ---


def test_poll_emits_status_event_first_time() -> None:
    ch, _, _ = _channel(connect=True)
    messages = ch.poll()
    events = [m for m in messages if m.get("command") == "modbus.status"]
    assert events and events[0]["data"]["state"] == "connected"


def test_poll_returns_register_values() -> None:
    blocks = [RegisterBlock("regs", RegisterKind.HOLDING, 0, 2)]
    ch, _, fake = _channel(blocks=blocks)
    fake.holding = {0: 11, 1: 22}
    messages = ch.poll()
    data_msgs = [m for m in messages if m.get("command") == "modbus.values"]
    assert data_msgs and data_msgs[0]["data"]["regs"] == [11, 22]


def test_poll_status_event_only_on_change() -> None:
    ch, _, _ = _channel()
    ch.poll()  # первое — событие смены состояния
    second = [m for m in ch.poll() if m.get("command") == "modbus.status"]
    assert second == []  # без изменений — повторного события нет


def test_poll_no_values_when_disconnected() -> None:
    blocks = [RegisterBlock("regs", RegisterKind.HOLDING, 0, 1)]
    ch, _, _ = _channel(blocks=blocks, connect=False)
    data_msgs = [m for m in ch.poll() if m.get("command") == "modbus.values"]
    assert data_msgs == []


# --- lifecycle / info ---


def test_get_info_shape() -> None:
    ch, _, _ = _channel()
    info = ch.get_info()
    assert info["type"] == "modbus"
    assert info["name"] == "modbus_1"
    assert "device" in info


def test_specs_blocks_accepted() -> None:
    ch, _, fake = _channel(blocks=[{"name": "a", "kind": "holding", "address": 0, "count": 1}])
    fake.holding = {0: 9}
    data = [m for m in ch.poll() if m.get("command") == "modbus.values"]
    assert data[0]["data"]["a"] == [9]
