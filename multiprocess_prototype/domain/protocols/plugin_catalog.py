# -*- coding: utf-8 -*-
"""
domain/protocols/plugin_catalog.py — Protocol для реестра плагинов (read-only).

PluginCatalog — минимальный контракт, который domain ждёт от внешнего
PluginRegistry (из Plugins/ или multiprocess_framework). Phase C создаст
адаптер PluginRegistryAdapter, оборачивающий реальный реестр в этот Protocol.

Sidecar-dataclasses:
  PortSpec   — описание одного порта плагина (имя + тип данных).
  PluginSpec — описание плагина (имя, категория, схема конфига, порты).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PortSpec:
    """Описание одного порта плагина (входного или выходного).

    direction — направление порта: "input" или "output".
    optional  — порт может быть не подключён (соответствует Port.optional).
    shape     — шаблон размерности, например "(H, W, 3)" (соответствует Port.shape).
    """

    name: str
    dtype: str
    direction: str = "input"
    optional: bool = False
    shape: str = ""


@dataclass(frozen=True, slots=True)
class PluginSpec:
    """Описание плагина из реестра.

    description   — человекочитаемое описание плагина (соответствует PluginEntry.description).
    config_schema — схема конфигурации в виде dict (опциональная).
    ports         — tuple входных/выходных портов.
    has_registers — плагин регистрирует доменные классы (bool(entry.register_classes)).
    """

    name: str
    category: str
    description: str = ""
    config_schema: dict[str, Any] = field(default_factory=dict)
    ports: tuple[PortSpec, ...] = ()
    has_registers: bool = False


class PluginCatalog(Protocol):
    """Контракт для read-only доступа к реестру плагинов.

    Реализации: PluginRegistryAdapter (Phase C), _FakePluginCatalog (тесты).
    """

    def list_plugins(self) -> tuple[PluginSpec, ...]:
        """Вернуть все доступные плагины."""
        ...

    def resolve(self, plugin_name: str) -> PluginSpec | None:
        """Найти плагин по имени. Возвращает None если не найден."""
        ...

    def categories(self) -> tuple[str, ...]:
        """Вернуть уникальные категории всех плагинов."""
        ...


__all__ = [
    "PortSpec",
    "PluginSpec",
    "PluginCatalog",
]
