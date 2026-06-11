"""Фабрика транспортов — build_transport (Р4 плана device-hub).

Строит RegisterTransport по DeviceEntry.transport:
    tcp    -> ModbusDevice(ModbusConfig(tcp, host, port, unit_id, tcp_nodelay))
    rtu    -> ModbusDevice(rtu, serial, baudrate, parity)
    bridge -> resolve_device(bridge_id) -> драйвер-носитель -> его RegisterTransport

Валидация: bridge-цикл (устройство ссылается само на себя или транзитивно),
носитель должен быть kind=robot и существовать в реестре.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from Services.device_hub.errors import TransportBuildError

if TYPE_CHECKING:
    from Services.modbus.interfaces import RegisterTransport


def build_transport(
    entry: Any,
    resolve_device: Callable[[str], Any],
) -> "RegisterTransport":
    """Построить транспорт для устройства.

    Args:
        entry:          DeviceEntry (duck-typed для тестируемости).
        resolve_device: Функция ``(id) -> driver``, резолвит устройство по id.
                        Для bridge-устройств возвращает драйвер-носитель.

    Returns:
        RegisterTransport для дальнейшего использования клиентом.

    Raises:
        TransportBuildError: Неверный тип, цикл, носитель не найден и т.п.
    """
    transport = entry.transport
    t_type = transport.get("type", "")

    if t_type == "tcp":
        return _build_tcp(transport)
    elif t_type == "rtu":
        return _build_rtu(transport)
    elif t_type == "bridge":
        return _build_bridge(entry, transport, resolve_device)
    else:
        raise TransportBuildError(f"Неизвестный transport.type: {t_type!r} для устройства {entry.id!r}")


def _build_tcp(transport: dict) -> "RegisterTransport":
    """TCP -> ModbusDevice с ModbusConfig."""
    from Services.modbus import ModbusConfig, ModbusDevice, TransportType

    host = transport.get("host", "127.0.0.1")
    port = int(transport.get("port", 502))
    unit_id = int(transport.get("unit_id", 1))
    timeout_sec = float(transport.get("timeout_sec", 1.0))
    retries = int(transport.get("retries", 1))
    tcp_nodelay = bool(transport.get("tcp_nodelay", True))
    word_order = str(transport.get("word_order", "big"))

    config = ModbusConfig(
        transport=TransportType.TCP,
        host=host,
        port=port,
        unit_id=unit_id,
        timeout_sec=timeout_sec,
        retries=retries,
        tcp_nodelay=tcp_nodelay,
        word_order=word_order,
    )
    return ModbusDevice(config)


def _build_rtu(transport: dict) -> "RegisterTransport":
    """RTU -> ModbusDevice с ModbusConfig (закладка — без железа)."""
    from Services.modbus import ModbusConfig, ModbusDevice, TransportType

    config = ModbusConfig(
        transport=TransportType.RTU,
        serial_port=str(transport.get("serial_port", "COM1")),
        baudrate=int(transport.get("baudrate", 9600)),
        parity=str(transport.get("parity", "N")),
        stopbits=int(transport.get("stopbits", 1)),
        bytesize=int(transport.get("bytesize", 8)),
        unit_id=int(transport.get("unit_id", 1)),
        timeout_sec=float(transport.get("timeout_sec", 1.0)),
        retries=int(transport.get("retries", 1)),
        word_order=str(transport.get("word_order", "big")),
    )
    return ModbusDevice(config)


def _build_bridge(
    entry: Any,
    transport: dict,
    resolve_device: Callable[[str], Any],
) -> "RegisterTransport":
    """Bridge -> RegisterTransport носителя-робота.

    Валидация:
    - bridge-id не совпадает с id самого устройства (прямой цикл)
    - носитель существует (resolve_device не вернул None)
    - носитель kind=robot (только роботы могут быть мостами)
    """
    bridge_id = transport.get("bridge", "")
    if not bridge_id:
        raise TransportBuildError(
            f"Устройство {entry.id!r}: bridge-транспорт требует поле 'bridge' (id устройства-носителя)"
        )

    # Проверка прямого цикла
    if bridge_id == entry.id:
        raise TransportBuildError(f"Устройство {entry.id!r}: bridge-цикл — ссылается на самого себя")

    # Резолвим носителя
    carrier = resolve_device(bridge_id)
    if carrier is None:
        raise TransportBuildError(f"Устройство {entry.id!r}: носитель {bridge_id!r} не найден в реестре")

    # Проверка kind носителя — только robot может быть мостом
    carrier_kind = getattr(carrier, "kind", None)
    if carrier_kind != "robot":
        raise TransportBuildError(
            f"Устройство {entry.id!r}: носитель {bridge_id!r} имеет kind={carrier_kind!r}, "
            f"а bridge-мостом может быть только kind=robot"
        )

    # Транспорт носителя — его RegisterTransport (RobotClient реализует его)
    transport_obj = getattr(carrier, "transport", None)
    if transport_obj is None:
        raise TransportBuildError(f"Устройство {entry.id!r}: у носителя {bridge_id!r} нет транспорта (не подключён?)")

    return transport_obj
