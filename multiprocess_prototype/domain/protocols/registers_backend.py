# -*- coding: utf-8 -*-
"""
domain/protocols/registers_backend.py — Protocol для доступа к регистрам Inspector.

RegistersBackend — минимальный контракт для чтения и записи значений полей
плагинов из Inspector-панели. Phase C создаст адаптер RegistersManagerAdapter
поверх существующего RegistersManager.

Sidecar-dataclasses:
  FieldSpec — описание поля регистра (имя, тип данных, метка, метаданные).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Описание одного поля регистра плагина.

    name     — имя поля (ключ в config).
    dtype    — строковое обозначение типа данных (например, 'int', 'float', 'str').
    label    — человекочитаемая метка для отображения в Inspector.
    metadata — произвольные дополнительные метаданные (например, min/max/step).
    """

    name: str
    dtype: str
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class RegistersBackend(Protocol):
    """Контракт для доступа к регистрам (значениям полей конфигурации плагинов).

    Реализации: RegistersManagerAdapter (Phase C), _FakeRegistersBackend (тесты).
    """

    def get_field_specs(
        self,
        process_name: str,
        plugin_index: int,
    ) -> tuple[FieldSpec, ...]:
        """Получить список описаний полей для плагина по индексу в процессе."""
        ...

    def get_value(
        self,
        process_name: str,
        plugin_index: int,
        field: str,
    ) -> Any:
        """Получить текущее значение поля плагина."""
        ...

    def set_value(
        self,
        process_name: str,
        plugin_index: int,
        field: str,
        value: Any,
    ) -> None:
        """Установить значение поля плагина."""
        ...


__all__ = [
    "FieldSpec",
    "RegistersBackend",
]
