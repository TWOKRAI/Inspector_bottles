"""Тесты build_transport: tcp, rtu, bridge + ошибки (цикл, неверный kind, не найден)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from Services.device_hub.errors import TransportBuildError
from Services.device_hub.transports import build_transport


@dataclass
class _FakeEntry:
    """Минимальная заглушка DeviceEntry для тестов транспорта."""

    id: str = "test_dev"
    kind: str = "robot"
    transport: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)


@dataclass
class _FakeCarrier:
    """Заглушка драйвера-носителя."""

    kind: str = "robot"
    transport: object = None


class TestBuildTransportTcp:
    """TCP-транспорт."""

    def test_tcp_creates_modbus_device(self) -> None:
        """tcp -> ModbusDevice с правильным конфигом (без реального connect)."""
        entry = _FakeEntry(transport={"type": "tcp", "host": "10.0.0.1", "port": 503, "unit_id": 5})
        device = build_transport(entry, lambda _: None)
        # ModbusDevice создан
        from Services.modbus import ModbusDevice

        assert isinstance(device, ModbusDevice)
        assert device.config.host == "10.0.0.1"
        assert device.config.port == 503
        assert device.config.unit_id == 5

    def test_tcp_defaults(self) -> None:
        """tcp с минимальными параметрами использует дефолты."""
        entry = _FakeEntry(transport={"type": "tcp"})
        device = build_transport(entry, lambda _: None)
        from Services.modbus import ModbusDevice

        assert isinstance(device, ModbusDevice)
        assert device.config.host == "127.0.0.1"
        assert device.config.port == 502


class TestBuildTransportRtu:
    """RTU-транспорт (закладка)."""

    def test_rtu_creates_modbus_device(self) -> None:
        """rtu -> ModbusDevice с RTU-конфигом."""
        entry = _FakeEntry(
            transport={
                "type": "rtu",
                "serial_port": "COM3",
                "baudrate": 19200,
            }
        )
        device = build_transport(entry, lambda _: None)
        from Services.modbus import ModbusDevice, TransportType

        assert isinstance(device, ModbusDevice)
        assert device.config.transport == TransportType.RTU
        assert device.config.serial_port == "COM3"
        assert device.config.baudrate == 19200


class TestBuildTransportBridge:
    """Bridge-транспорт."""

    def test_bridge_returns_carrier_transport(self) -> None:
        """bridge -> RegisterTransport носителя."""
        fake_transport = object()  # заглушка RegisterTransport
        carrier = _FakeCarrier(kind="robot", transport=fake_transport)
        entry = _FakeEntry(
            id="vfd_1",
            kind="vfd",
            transport={"type": "bridge", "bridge": "robot_main"},
        )
        result = build_transport(entry, lambda _: carrier)
        assert result is fake_transport

    def test_bridge_cycle_direct(self) -> None:
        """Прямой цикл: bridge ссылается на себя -> ошибка."""
        entry = _FakeEntry(
            id="dev_1",
            transport={"type": "bridge", "bridge": "dev_1"},
        )
        with pytest.raises(TransportBuildError, match="цикл"):
            build_transport(entry, lambda _: None)

    def test_bridge_carrier_not_found(self) -> None:
        """Носитель не найден -> ошибка."""
        entry = _FakeEntry(
            id="vfd_1",
            transport={"type": "bridge", "bridge": "nonexistent"},
        )
        with pytest.raises(TransportBuildError, match="не найден"):
            build_transport(entry, lambda _: None)

    def test_bridge_carrier_wrong_kind(self) -> None:
        """Носитель не robot -> ошибка."""
        carrier = _FakeCarrier(kind="vfd", transport=object())
        entry = _FakeEntry(
            id="vfd_1",
            transport={"type": "bridge", "bridge": "vfd_other"},
        )
        with pytest.raises(TransportBuildError, match="только kind=robot"):
            build_transport(entry, lambda _: carrier)

    def test_bridge_carrier_no_transport(self) -> None:
        """Носитель без транспорта (не подключён) -> ошибка."""
        carrier = _FakeCarrier(kind="robot", transport=None)
        entry = _FakeEntry(
            id="vfd_1",
            transport={"type": "bridge", "bridge": "robot_main"},
        )
        with pytest.raises(TransportBuildError, match="нет транспорта"):
            build_transport(entry, lambda _: carrier)

    def test_bridge_empty_id(self) -> None:
        """Пустой bridge id -> ошибка."""
        entry = _FakeEntry(
            id="vfd_1",
            transport={"type": "bridge", "bridge": ""},
        )
        with pytest.raises(TransportBuildError, match="bridge"):
            build_transport(entry, lambda _: None)


class TestBuildTransportErrors:
    """Ошибки общего характера."""

    def test_unknown_type(self) -> None:
        """Неизвестный transport.type -> ошибка."""
        entry = _FakeEntry(transport={"type": "bluetooth"})
        with pytest.raises(TransportBuildError, match="Неизвестный"):
            build_transport(entry, lambda _: None)

    def test_empty_type(self) -> None:
        """Пустой transport.type -> ошибка."""
        entry = _FakeEntry(transport={"type": ""})
        with pytest.raises(TransportBuildError, match="Неизвестный"):
            build_transport(entry, lambda _: None)
