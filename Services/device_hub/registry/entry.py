"""DeviceEntry -- запись реестра устройств (Р2 плана device-hub).

Dataclass + Dict-at-Boundary (НЕ SchemaBase — доменная сущность Services-слоя).
Валидация id (slug: [a-z0-9_]+), kind, transport.type при создании.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Допустимые значения kind (расширяемо — generic_modbus для произвольных устройств)
VALID_KINDS: frozenset[str] = frozenset({"robot", "vfd", "hikvision", "generic_modbus"})

# Допустимые типы транспорта
VALID_TRANSPORT_TYPES: frozenset[str] = frozenset({"tcp", "rtu", "bridge"})

# Паттерн slug: только строчные латинские + цифры + подчёркивание
_ID_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass
class DeviceEntry:
    """Запись реестра устройств.

    Attributes:
        id:           Уникальный slug (``[a-z0-9_]+``).
        name:         Человекочитаемое имя для GUI.
        kind:         Тип устройства: ``robot`` | ``vfd`` | ``hikvision`` | ``generic_modbus``.
        protocol:     Имя протокола без .yaml; пустая строка для hikvision.
        transport:    Параметры транспорта: ``{type: tcp|rtu|bridge, ...}``.
        params:       Kind-специфичные параметры.
        enabled:      Включено ли устройство.
        auto_connect: Автоподключение при старте процесса devices.
        origin:       Источник записи: ``manual`` | ``recipe:<slug>``.
    """

    id: str
    name: str
    kind: str
    protocol: str = ""
    transport: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    enabled: bool = True
    auto_connect: bool = False
    origin: str = "manual"

    def __post_init__(self) -> None:
        """Валидация полей при создании."""
        self._validate()

    def _validate(self) -> None:
        """Проверить id/kind/transport.type."""
        if not isinstance(self.id, str) or not _ID_RE.match(self.id):
            raise ValueError(f"DeviceEntry.id должен быть slug [a-z0-9_]+, получено: {self.id!r}")
        if self.kind not in VALID_KINDS:
            raise ValueError(f"DeviceEntry.kind {self.kind!r} не из {sorted(VALID_KINDS)}")
        t_type = self.transport.get("type", "")
        if t_type and t_type not in VALID_TRANSPORT_TYPES:
            raise ValueError(f"DeviceEntry.transport.type {t_type!r} не из {sorted(VALID_TRANSPORT_TYPES)}")

    # ------------------------------------------------------------------ #
    # Dict at Boundary
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "protocol": self.protocol,
            "transport": dict(self.transport),
            "params": dict(self.params),
            "enabled": self.enabled,
            "auto_connect": self.auto_connect,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceEntry":
        """Создать из dict, игнорируя посторонние ключи."""
        known = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
