"""Периодический опрос блоков регистров.

Описывает, ЧТО опрашивать (список RegisterBlock), и выполняет один проход опроса
через ModbusDevice, возвращая срез значений. Сам цикл/таймер не держит — его
обеспечивает worker плагина (или вызывающий код). Это сохраняет core свободным
от потоковой инфраструктуры и легко тестируемым.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from Services.modbus.core.device import ModbusDevice


class RegisterKind(str, Enum):
    """Тип читаемого блока Modbus."""

    HOLDING = "holding"
    INPUT = "input"
    COILS = "coils"
    DISCRETE = "discrete"


@dataclass(slots=True)
class RegisterBlock:
    """Описание блока для опроса.

    Attributes:
        name:    Логическое имя блока (ключ в результате).
        kind:    Тип блока (holding/input/coils/discrete).
        address: Начальный адрес.
        count:   Количество регистров/битов.
    """

    name: str
    kind: RegisterKind
    address: int
    count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RegisterKind):
            self.kind = RegisterKind(str(self.kind).lower())


_READERS = {
    RegisterKind.HOLDING: "read_holding",
    RegisterKind.INPUT: "read_input",
    RegisterKind.COILS: "read_coils",
    RegisterKind.DISCRETE: "read_discrete_inputs",
}


class ModbusPoller:
    """Опрашивает заданные блоки регистров одним проходом."""

    def __init__(self, device: ModbusDevice, blocks: list[RegisterBlock]) -> None:
        self._device = device
        self._blocks = list(blocks)

    @property
    def blocks(self) -> list[RegisterBlock]:
        """Список опрашиваемых блоков."""
        return list(self._blocks)

    def poll_once(self) -> dict[str, Any]:
        """Прочитать все блоки. Возвращает {name: values | {"error": msg}}.

        Ошибка чтения отдельного блока не прерывает опрос остальных — она
        фиксируется в результате этого блока и в телеметрии устройства.
        """
        result: dict[str, Any] = {}
        for block in self._blocks:
            reader = getattr(self._device, _READERS[block.kind])
            try:
                result[block.name] = reader(block.address, block.count)
            except Exception as exc:  # noqa: BLE001 - изоляция блоков
                result[block.name] = {"error": str(exc)}
        return result

    @classmethod
    def from_specs(cls, device: ModbusDevice, specs: list[dict[str, Any]]) -> "ModbusPoller":
        """Создать poller из списка dict-описаний (Dict at Boundary / YAML)."""
        blocks = [
            RegisterBlock(
                name=s["name"],
                kind=s.get("kind", "holding"),
                address=int(s["address"]),
                count=int(s.get("count", 1)),
            )
            for s in specs
        ]
        return cls(device, blocks)
