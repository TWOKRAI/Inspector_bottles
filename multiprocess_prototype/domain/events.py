# -*- coding: utf-8 -*-
"""
domain/events.py — типизированные доменные события (Phase B / Task B.2).

Каждое событие — immutable dataclass с ClassVar[str] event_type-дискриминатором.
ProjectEvent = discriminated union всех 14 событий.

Использование в presenter'е:
    def _on_event(evt: ProjectEvent) -> None:
        match evt:
            case ProcessAdded(process_name=name):
                ...
            case WireConnected(wire=wire):
                ...

Дискриминатор event_type зарезервирован для сериализации в Phase F.
Не является полем dataclass — хранится в ClassVar для экономии памяти (slots=True).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Union

from multiprocess_prototype.domain.entities.display import DisplayInstance
from multiprocess_prototype.domain.entities.plugin import PluginInstance
from multiprocess_prototype.domain.entities.process import Process
from multiprocess_prototype.domain.entities.wire import Wire

# ==============================================================================
# Process-события
# ==============================================================================


@dataclass(frozen=True, slots=True)
class ProcessAdded:
    """Эмитится когда новый Process добавлен в топологию."""

    event_type: ClassVar[str] = "ProcessAdded"

    process_name: str
    process: Process


@dataclass(frozen=True, slots=True)
class ProcessRemoved:
    """Эмитится когда Process удалён из топологии (вместе с зависимыми Wire и Display)."""

    event_type: ClassVar[str] = "ProcessRemoved"

    process_name: str


@dataclass(frozen=True, slots=True)
class ProcessRenamed:
    """Эмитится когда Process переименован."""

    event_type: ClassVar[str] = "ProcessRenamed"

    old_name: str
    new_name: str


# ==============================================================================
# Plugin-события
# ==============================================================================


@dataclass(frozen=True, slots=True)
class PluginInserted:
    """Эмитится когда PluginInstance вставлен в цепочку плагинов процесса."""

    event_type: ClassVar[str] = "PluginInserted"

    process_name: str
    plugin: PluginInstance
    index: int


@dataclass(frozen=True, slots=True)
class PluginRemoved:
    """Эмитится когда PluginInstance удалён из цепочки плагинов процесса."""

    event_type: ClassVar[str] = "PluginRemoved"

    process_name: str
    plugin_name: str
    index: int


@dataclass(frozen=True, slots=True)
class PluginConfigChanged:
    """Эмитится когда значение поля конфигурации PluginInstance изменено."""

    event_type: ClassVar[str] = "PluginConfigChanged"

    process_name: str
    plugin_index: int
    field: str
    value: Any


# ==============================================================================
# Wire-события
# ==============================================================================


@dataclass(frozen=True, slots=True)
class WireConnected:
    """Эмитится когда Wire добавлен в топологию."""

    event_type: ClassVar[str] = "WireConnected"

    wire: Wire


@dataclass(frozen=True, slots=True)
class WireDisconnected:
    """Эмитится когда Wire удалён из топологии."""

    event_type: ClassVar[str] = "WireDisconnected"

    source: str
    target: str


# ==============================================================================
# Display-события
# ==============================================================================


@dataclass(frozen=True, slots=True)
class DisplayBound:
    """Эмитится когда DisplayInstance привязан к узлу топологии."""

    event_type: ClassVar[str] = "DisplayBound"

    display: DisplayInstance


@dataclass(frozen=True, slots=True)
class DisplayUnbound:
    """Эмитится когда DisplayInstance отвязан от узла топологии.

    Несёт пару (node_id, display_id) — отвязка адресует конкретную привязку,
    а не все привязки узла (fan-out). См. ADR DOM-001.
    """

    event_type: ClassVar[str] = "DisplayUnbound"

    node_id: str
    display_id: str


# ==============================================================================
# Target / Recipe / Topology-события
# ==============================================================================


@dataclass(frozen=True, slots=True)
class TargetProcessAssigned:
    """Эмитится когда целевой процесс (target_process) назначен или сброшен для Process."""

    event_type: ClassVar[str] = "TargetProcessAssigned"

    process_name: str
    target: str | None


@dataclass(frozen=True, slots=True)
class RecipeActivated:
    """Эмитится когда Recipe активирован (slug стал активным)."""

    event_type: ClassVar[str] = "RecipeActivated"

    slug: str


@dataclass(frozen=True, slots=True)
class RecipeDeactivated:
    """Эмитится когда активный Recipe сброшен (нет активного рецепта)."""

    event_type: ClassVar[str] = "RecipeDeactivated"


@dataclass(frozen=True, slots=True)
class TopologyReplaced:
    """Эмитится при катастрофической замене топологии (recipe launch / blueprint reload).

    Подписчик должен выполнить полный refresh своего состояния.
    """

    event_type: ClassVar[str] = "TopologyReplaced"

    reason: str


# ==============================================================================
# Discriminated union всех 14 событий
# ==============================================================================

ProjectEvent = Union[
    ProcessAdded,
    ProcessRemoved,
    ProcessRenamed,
    PluginInserted,
    PluginRemoved,
    PluginConfigChanged,
    WireConnected,
    WireDisconnected,
    DisplayBound,
    DisplayUnbound,
    TargetProcessAssigned,
    RecipeActivated,
    RecipeDeactivated,
    TopologyReplaced,
]

__all__ = [
    # Конкретные события
    "ProcessAdded",
    "ProcessRemoved",
    "ProcessRenamed",
    "PluginInserted",
    "PluginRemoved",
    "PluginConfigChanged",
    "WireConnected",
    "WireDisconnected",
    "DisplayBound",
    "DisplayUnbound",
    "TargetProcessAssigned",
    "RecipeActivated",
    "RecipeDeactivated",
    "TopologyReplaced",
    # Union-тип
    "ProjectEvent",
]
