"""Конфигурация подключения Modbus.

Транспорт-агностичный конфиг: один и тот же ModbusConfig описывает и TCP,
и RS485 (RTU). Поле ``transport`` выбирает, какие параметры значимы:

- ``tcp``  → host, port
- ``rtu``  → serial_port, baudrate, parity, stopbits, bytesize

Это plain dataclass (не Pydantic) — core-слой не тянет тяжёлых зависимостей и
сериализуется через ``to_dict``/``from_dict`` (правило Dict at Boundary).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class TransportType(str, Enum):
    """Тип транспорта Modbus."""

    TCP = "tcp"
    RTU = "rtu"  # RS485 / последовательный


@dataclass(slots=True)
class ModbusConfig:
    """Параметры подключения и поведения Modbus-клиента.

    Attributes:
        transport:   ``tcp`` или ``rtu`` (RS485).
        host:        IP/hostname устройства (TCP).
        port:        TCP-порт (стандарт Modbus-TCP — 502).
        serial_port: Имя последовательного порта (RTU), напр. ``COM3`` / ``/dev/ttyUSB0``.
        baudrate:    Скорость (RTU).
        parity:      Чётность (RTU): ``N`` | ``E`` | ``O``.
        stopbits:    Стоп-биты (RTU).
        bytesize:    Размер байта (RTU).
        unit_id:     Адрес ведомого устройства (Modbus unit / slave / device_id).
        timeout_sec: Таймаут операции, сек.
        retries:     Число повторов на операцию.
        word_order:  Порядок слов для 32-битных типов: ``big`` | ``little``.
        tcp_nodelay: Отключить алгоритм Нейгла (TCP) — убирает ~40 мс лагов
                     при частых мелких записях (боевой опыт с роботом Delta).
    """

    transport: TransportType = TransportType.TCP

    # TCP
    host: str = "127.0.0.1"
    port: int = 502
    tcp_nodelay: bool = True

    # RTU / RS485
    serial_port: str = "COM1"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8

    # Общее
    unit_id: int = 1
    timeout_sec: float = 3.0
    retries: int = 3
    word_order: str = "big"

    def __post_init__(self) -> None:
        # Нормализация transport из строки (приходит из YAML/dict как str)
        if not isinstance(self.transport, TransportType):
            self.transport = TransportType(str(self.transport).lower())

    # ------------------------------------------------------------------ #
    # Dict at Boundary
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict (transport как строка)."""
        data = asdict(self)
        data["transport"] = self.transport.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModbusConfig":
        """Создать из dict, игнорируя посторонние ключи."""
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def describe(self) -> str:
        """Человекочитаемый адрес назначения (для логов/UI)."""
        if self.transport is TransportType.TCP:
            return f"tcp://{self.host}:{self.port}#unit{self.unit_id}"
        return f"rtu://{self.serial_port}@{self.baudrate}#unit{self.unit_id}"
