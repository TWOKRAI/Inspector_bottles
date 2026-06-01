"""Тесты ModbusSinkPlugin — lifecycle, запись метаданных кадра (без pymodbus/железа)."""

from __future__ import annotations


from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.tests.conftest import FakeSdkClient

from Plugins.sinks.modbus_sink.plugin import ModbusSinkPlugin


def _make_plugin(config: dict | None = None) -> tuple[ModbusSinkPlugin, PluginContext]:
    services = MockProcessServices(name="modbus_sink_proc", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = ModbusSinkPlugin()
    plugin.configure(ctx)
    return plugin, ctx


def _attach_connected_device(plugin: ModbusSinkPlugin) -> FakeSdkClient:
    """Подключить fake-устройство к плагину (минуя реальную сеть в start())."""
    fake = FakeSdkClient()
    dev = ModbusDevice(ModbusConfig(), client=fake)
    dev.connect()
    plugin._device = dev
    return fake


# --- lifecycle / config ---


def test_configure_creates_register_with_defaults() -> None:
    plugin, _ = _make_plugin()
    assert plugin._reg.port == 5020
    assert plugin._reg.base_address == 100


def test_config_overrides_applied() -> None:
    plugin, _ = _make_plugin({"host": "10.0.0.5", "port": 1502, "base_address": 200})
    assert plugin._reg.host == "10.0.0.5"
    assert plugin._reg.port == 1502
    assert plugin._reg.base_address == 200


# --- process: запись метаданных ---


def test_process_is_pass_through() -> None:
    plugin, _ = _make_plugin()
    _attach_connected_device(plugin)
    items = [{"width": 640, "height": 480, "frame_id": 1}]
    assert plugin.process(items) is items


def test_process_writes_width_height_frameid() -> None:
    plugin, _ = _make_plugin()
    fake = _attach_connected_device(plugin)
    plugin.process([{"width": 640, "height": 480, "frame_id": 7}])
    # base_address=100 → [100]=width, [101]=height, [102]=frame_id
    assert fake.holding[100] == 640
    assert fake.holding[101] == 480
    assert fake.holding[102] == 7
    assert plugin._reg.writes_ok == 1
    assert plugin._reg.last_written == "[640, 480, 7]"


def test_frame_id_clamped_to_u16() -> None:
    plugin, _ = _make_plugin()
    fake = _attach_connected_device(plugin)
    plugin.process([{"width": 1, "height": 1, "frame_id": 65536 + 5}])
    assert fake.holding[102] == 5  # 65541 % 65536


def test_size_falls_back_to_frame_shape() -> None:
    import numpy as np

    plugin, _ = _make_plugin()
    fake = _attach_connected_device(plugin)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)  # H=48, W=64
    plugin.process([{"frame": frame, "seq_id": 3}])
    assert fake.holding[100] == 64  # width
    assert fake.holding[101] == 48  # height
    assert fake.holding[102] == 3  # seq_id как frame_id


def test_write_every_n_throttles() -> None:
    plugin, _ = _make_plugin({"write_every_n": 3})
    _attach_connected_device(plugin)
    for fid in range(6):
        plugin.process([{"width": 10, "height": 10, "frame_id": fid}])
    # Пишутся только кадры 3-й и 6-й (frame_counter % 3 == 0)
    assert plugin._reg.writes_ok == 2
    assert plugin._reg.frames_seen == 6


def test_process_skips_when_no_device() -> None:
    plugin, _ = _make_plugin()
    # device не подключён (start не вызван) → не падаем, frames_seen растёт
    result = plugin.process([{"width": 640, "height": 480, "frame_id": 1}])
    assert result == [{"width": 640, "height": 480, "frame_id": 1}]
    assert plugin._reg.frames_seen == 1
    assert plugin._reg.writes_ok == 0


def test_process_skips_when_reconnect_fails() -> None:
    plugin, _ = _make_plugin()
    fake = _attach_connected_device(plugin)
    plugin._device.disconnect()
    fake.fail_connect = True  # приёмник недоступен → reconnect не удастся
    plugin.process([{"width": 640, "height": 480, "frame_id": 1}])
    assert fake.holding == {}
    assert plugin._reg.writes_ok == 0


def test_process_reconnects_when_receiver_returns() -> None:
    plugin, _ = _make_plugin()
    fake = _attach_connected_device(plugin)
    plugin._device.disconnect()  # приёмник «упал», потом поднялся (fake коннектится)
    plugin.process([{"width": 320, "height": 240, "frame_id": 9}])
    # throttled-reconnect восстановил соединение и записал кадр
    assert fake.holding[100] == 320
    assert plugin._reg.writes_ok == 1


# --- shutdown ---


def test_shutdown_disconnects_device() -> None:
    plugin, ctx = _make_plugin()
    _attach_connected_device(plugin)
    plugin.shutdown(ctx)
    assert plugin._device is None
