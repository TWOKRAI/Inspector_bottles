"""Тесты ModbusSinkPlugin — универсальный payload, запись в регистры (без pymodbus/железа)."""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.modbus.sdk.datatypes import decode_uint32
from Services.modbus.tests.conftest import FakeSdkClient

from Plugins.sinks.modbus_sink.plugin import ModbusSinkPlugin


def _make_plugin(config: dict | None = None) -> ModbusSinkPlugin:
    services = MockProcessServices(name="modbus_sink_proc", config=config or {})
    ctx = PluginContext(services=services, config=config or {})
    plugin = ModbusSinkPlugin()
    plugin.configure(ctx)
    return plugin


def _attach_connected_device(plugin: ModbusSinkPlugin) -> FakeSdkClient:
    fake = FakeSdkClient()
    dev = ModbusDevice(ModbusConfig(), client=fake)
    dev.connect()
    plugin._device = dev
    return fake


# --- lifecycle / config ---


def test_configure_defaults() -> None:
    plugin = _make_plugin()
    assert plugin._reg.port == 5020
    assert plugin._reg.base_address == 100
    assert len(plugin._reg.payload) == 6  # w,h,fid,count,area_sum,area_max


def test_config_overrides_applied() -> None:
    plugin = _make_plugin({"host": "10.0.0.5", "port": 1502, "base_address": 200})
    assert plugin._reg.host == "10.0.0.5"
    assert plugin._reg.port == 1502
    assert plugin._reg.base_address == 200


# --- process: pass-through ---


def test_process_is_pass_through() -> None:
    plugin = _make_plugin()
    _attach_connected_device(plugin)
    items = [{"width": 640, "height": 480, "frame_id": 1}]
    assert plugin.process(items) is items


# --- default payload ---


def test_default_payload_no_detections() -> None:
    plugin = _make_plugin()
    fake = _attach_connected_device(plugin)
    plugin.process([{"width": 640, "height": 480, "frame_id": 7}])
    # base=100: w,h,fid,count(=0),area_sum(u32=0→2рег),area_max(u32=0→2рег)
    assert fake.holding[100] == 640
    assert fake.holding[101] == 480
    assert fake.holding[102] == 7
    assert fake.holding[103] == 0  # count
    assert decode_uint32([fake.holding[104], fake.holding[105]]) == 0  # area_sum
    assert decode_uint32([fake.holding[106], fake.holding[107]]) == 0  # area_max
    assert plugin._reg.writes_ok == 1


def test_default_payload_with_detections_area_u32() -> None:
    plugin = _make_plugin()
    fake = _attach_connected_device(plugin)
    dets = [{"area": 100000}, {"area": 50000}]  # площади > 65535 → нужен u32
    plugin.process([{"width": 640, "height": 480, "frame_id": 1, "detections": dets}])
    assert fake.holding[103] == 2  # count
    assert decode_uint32([fake.holding[104], fake.holding[105]]) == 150000  # area_sum
    assert decode_uint32([fake.holding[106], fake.holding[107]]) == 100000  # area_max


def test_frame_id_wraps_u16() -> None:
    plugin = _make_plugin()
    fake = _attach_connected_device(plugin)
    plugin.process([{"width": 1, "height": 1, "frame_id": 65536 + 5}])
    assert fake.holding[102] == 5  # encode_uint16 маскирует


# --- универсальность: произвольный payload ---


def test_custom_payload_arbitrary_fields() -> None:
    payload = [
        {"source": "temperature"},
        {"source": "frame_id"},
    ]
    plugin = _make_plugin({"payload": payload, "base_address": 10})
    fake = _attach_connected_device(plugin)
    plugin.process([{"temperature": 42, "frame_id": 99}])
    assert fake.holding[10] == 42
    assert fake.holding[11] == 99


def test_custom_payload_sum_over_field() -> None:
    payload = [{"source": "boxes", "reduce": "sum", "field": "w", "dtype": "u16"}]
    plugin = _make_plugin({"payload": payload, "base_address": 0})
    fake = _attach_connected_device(plugin)
    plugin.process([{"boxes": [{"w": 10}, {"w": 20}, {"w": 30}]}])
    assert fake.holding[0] == 60


def test_missing_field_writes_zero() -> None:
    plugin = _make_plugin({"payload": [{"source": "nope"}], "base_address": 5})
    fake = _attach_connected_device(plugin)
    plugin.process([{"width": 1}])
    assert fake.holding[5] == 0


# --- троттлинг / соединение ---


def test_write_every_n_throttles() -> None:
    plugin = _make_plugin({"write_every_n": 3})
    _attach_connected_device(plugin)
    for fid in range(6):
        plugin.process([{"width": 10, "height": 10, "frame_id": fid}])
    assert plugin._reg.writes_ok == 2
    assert plugin._reg.frames_seen == 6


def test_process_skips_when_no_device() -> None:
    plugin = _make_plugin()
    result = plugin.process([{"width": 640, "height": 480, "frame_id": 1}])
    assert result == [{"width": 640, "height": 480, "frame_id": 1}]
    assert plugin._reg.frames_seen == 1
    assert plugin._reg.writes_ok == 0


def test_process_skips_when_reconnect_fails() -> None:
    plugin = _make_plugin()
    fake = _attach_connected_device(plugin)
    plugin._device.disconnect()
    fake.fail_connect = True
    plugin.process([{"width": 640, "height": 480, "frame_id": 1}])
    assert fake.holding == {}
    assert plugin._reg.writes_ok == 0


def test_process_reconnects_when_receiver_returns() -> None:
    plugin = _make_plugin()
    fake = _attach_connected_device(plugin)
    plugin._device.disconnect()
    plugin.process([{"width": 320, "height": 240, "frame_id": 9}])
    assert fake.holding[100] == 320
    assert plugin._reg.writes_ok == 1


def test_shutdown_disconnects_device() -> None:
    services = MockProcessServices(name="modbus_sink_proc", config={})
    ctx = PluginContext(services=services, config={})
    plugin = ModbusSinkPlugin()
    plugin.configure(ctx)
    _attach_connected_device(plugin)
    plugin.shutdown(ctx)
    assert plugin._device is None
