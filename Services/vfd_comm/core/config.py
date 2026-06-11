"""Конфиг сервиса vfd_comm.

SRP: только доменные параметры ПЧ (диапазон частот). Транспортных параметров
(host/port/serial) здесь НЕТ — транспорт внешний (мост RobotClient или
ModbusDevice), его конфигурирует владелец транспорта.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class VfdConfig:
    """Доменные параметры ПЧ INVT GD20.

    Attributes:
        freq_min_hz / freq_max_hz: Допустимый диапазон уставки частоты.
            GD20 по умолчанию 0..50 Гц; верх зависит от P00.03 (max frequency).
        default_freq_hz: Частота по умолчанию для run() без аргумента в UI.
        stale_polls_limit: Сколько подряд poll() без роста heartbeat зеркала
            считать обрывом моста (VfdBridgeStaleError из ensure_alive()).
    """

    freq_min_hz: float = 0.0
    freq_max_hz: float = 50.0
    default_freq_hz: float = 10.0
    stale_polls_limit: int = 5

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VfdConfig":
        """Создать из dict, игнорируя посторонние ключи."""
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})
