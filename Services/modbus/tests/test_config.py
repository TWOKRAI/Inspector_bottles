"""Тесты ModbusConfig — нормализация, сериализация, describe."""

from __future__ import annotations

from Services.modbus.core.config import ModbusConfig, TransportType


def test_defaults_tcp() -> None:
    cfg = ModbusConfig()
    assert cfg.transport is TransportType.TCP
    assert cfg.port == 502
    assert cfg.unit_id == 1


def test_transport_normalized_from_string() -> None:
    cfg = ModbusConfig(transport="rtu")  # type: ignore[arg-type]
    assert cfg.transport is TransportType.RTU


def test_to_dict_serializes_transport_as_str() -> None:
    data = ModbusConfig(transport=TransportType.RTU).to_dict()
    assert data["transport"] == "rtu"
    assert isinstance(data["transport"], str)


def test_from_dict_ignores_unknown_keys() -> None:
    cfg = ModbusConfig.from_dict({"host": "10.0.0.5", "port": 1502, "bogus": 99})
    assert cfg.host == "10.0.0.5"
    assert cfg.port == 1502


def test_roundtrip_dict() -> None:
    original = ModbusConfig(transport=TransportType.RTU, serial_port="COM3", baudrate=19200)
    restored = ModbusConfig.from_dict(original.to_dict())
    assert restored == original


def test_describe_tcp() -> None:
    assert ModbusConfig(host="1.2.3.4", port=502, unit_id=2).describe() == "tcp://1.2.3.4:502#unit2"


def test_describe_rtu() -> None:
    cfg = ModbusConfig(transport=TransportType.RTU, serial_port="COM3", baudrate=9600, unit_id=7)
    assert cfg.describe() == "rtu://COM3@9600#unit7"
