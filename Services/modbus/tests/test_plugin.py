"""Тесты ModbusPlugin — lifecycle, data flow, команды (без pymodbus/железа)."""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.plugin.plugin import ModbusPlugin

from .conftest import FakeSdkClient


def _make_plugin(config: dict | None = None) -> tuple[ModbusPlugin, PluginContext, MockProcessServices]:
    services = MockProcessServices(name="modbus_proc", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = ModbusPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services


def _connected_device() -> tuple[ModbusDevice, FakeSdkClient]:
    fake = FakeSdkClient()
    dev = ModbusDevice(ModbusConfig(), client=fake)
    dev.connect()
    return dev, fake


# --- lifecycle ---


def test_configure_creates_register() -> None:
    plugin, _, services = _make_plugin()
    assert plugin._reg.port == 502
    assert any("configured" in log["msg"] for log in services.logs)


def test_config_overrides_applied() -> None:
    plugin, _, _ = _make_plugin({"host": "10.0.0.9", "port": 1502, "poll_count": 4})
    assert plugin._reg.host == "10.0.0.9"
    assert plugin._reg.port == 1502
    assert plugin._reg.poll_count == 4


def test_start_registers_poll_worker() -> None:
    plugin, ctx, services = _make_plugin()
    plugin.start(ctx)
    created = services.worker_manager.calls["create_worker"]
    assert created and created[0][0] == "modbus_poll_worker"


# --- data flow (запись в PLC) ---


def test_process_pass_through_when_write_disabled() -> None:
    plugin, _, _ = _make_plugin()
    items = [{"verdict": 1}]
    assert plugin.process(items) is items


def test_process_writes_verdict_when_enabled() -> None:
    plugin, _, _ = _make_plugin()
    dev, fake = _connected_device()
    plugin._device = dev
    plugin._reg.write_enabled = True
    plugin._reg.write_address = 3
    plugin._reg.write_field = "verdict"
    plugin.process([{"verdict": 7}])
    assert fake.holding[3] == 7


def test_process_skips_item_without_field() -> None:
    plugin, _, _ = _make_plugin()
    dev, fake = _connected_device()
    plugin._device = dev
    plugin._reg.write_enabled = True
    plugin.process([{"other": 1}])
    assert fake.holding == {}


# --- команды ---


def test_cmd_read_registers_returns_values() -> None:
    plugin, _, _ = _make_plugin()
    dev, fake = _connected_device()
    fake.holding = {0: 100, 1: 200}
    plugin._device = dev
    result = plugin.cmd_read_registers({"address": 0, "count": 2})
    assert result["status"] == "ok"
    assert result["values"] == [100, 200]


def test_cmd_read_registers_not_connected() -> None:
    plugin, _, _ = _make_plugin()
    result = plugin.cmd_read_registers({})
    assert result["status"] == "error"


def test_cmd_write_register() -> None:
    plugin, _, _ = _make_plugin()
    dev, fake = _connected_device()
    plugin._device = dev
    result = plugin.cmd_write_register({"address": 5, "value": 42})
    assert result["status"] == "ok"
    assert fake.holding[5] == 42


def test_cmd_get_status_telemetry() -> None:
    plugin, _, _ = _make_plugin()
    dev, _ = _connected_device()
    plugin._device = dev
    status = plugin.cmd_get_status({})
    assert status["status"] == "ok"
    assert status["state"] == "connected"
    assert "reads_ok" in status


def test_cmd_get_status_no_device() -> None:
    plugin, _, _ = _make_plugin()
    status = plugin.cmd_get_status({})
    assert status["state"] == "disconnected"
    assert status["connected"] is False


# --- телеметрия ---


def test_sync_telemetry_copies_counters() -> None:
    plugin, _, _ = _make_plugin()
    dev, fake = _connected_device()
    fake.holding = {0: 1}
    plugin._device = dev
    dev.read_holding(0, 1)
    plugin._sync_telemetry()
    assert plugin._reg.reads_ok == 1
    assert plugin._reg.conn_state == "connected"


def test_poll_once_updates_last_values() -> None:
    plugin, _, _ = _make_plugin()
    dev, fake = _connected_device()
    fake.holding = {0: 11, 1: 22, 2: 33}
    plugin._device = dev
    plugin._reg.poll_address = 0
    plugin._reg.poll_count = 3
    plugin._poll_once()
    assert plugin._reg.last_values == "[11, 22, 33]"


@pytest.mark.parametrize("kind,reader", [("input", "read_input"), ("coils", "read_coils")])
def test_poll_kind_selects_reader(kind: str, reader: str) -> None:
    plugin, _, _ = _make_plugin()
    dev, fake = _connected_device()
    plugin._device = dev
    plugin._reg.poll_kind = kind
    plugin._reg.poll_count = 1
    plugin._poll_once()
    assert any(call[0] == reader for call in fake.calls)


# --- P4: регистрация канала в RouterManager ---


class _MockRouter:
    """Минимальный RouterManager-мок: фиксирует register/unregister_channel."""

    def __init__(self) -> None:
        self.channels: dict = {}

    def register_channel(self, channel) -> bool:
        self.channels[channel.name] = channel
        return True

    def unregister_channel(self, name: str) -> bool:
        return self.channels.pop(name, None) is not None


def test_start_registers_channel_when_router_present() -> None:
    router = _MockRouter()
    services = MockProcessServices(name="modbus_proc", router_manager=router)
    ctx = PluginContext(services=services, config={})
    plugin = ModbusPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    assert "modbus_1" in router.channels
    assert router.channels["modbus_1"].channel_type == "modbus"


def test_shutdown_unregisters_channel() -> None:
    router = _MockRouter()
    services = MockProcessServices(name="modbus_proc", router_manager=router)
    ctx = PluginContext(services=services, config={})
    plugin = ModbusPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    plugin.shutdown(ctx)
    assert "modbus_1" not in router.channels


def test_no_channel_without_router() -> None:
    plugin, ctx, _ = _make_plugin()
    plugin.start(ctx)
    assert plugin._channel is None
