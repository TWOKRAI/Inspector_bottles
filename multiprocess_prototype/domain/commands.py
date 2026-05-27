# -*- coding: utf-8 -*-
"""
domain/commands.py — типизированные доменные команды (Phase B / Task B.3).

Каждая команда — immutable dataclass с ClassVar[str] command_type-дискриминатором.
ProjectCommand = discriminated union всех 14 команд.

Команды — «намерение» presenter'а изменить состояние Project.
Валидация и инварианты — ответственность Project.apply() (Task B.4).

Использование в presenter'е:
    cmd: ProjectCommand = AddProcess(process_name="my_proc")
    new_project, events = project.apply(cmd, catalogs=services)

Pattern-match в обработчике:
    def _dispatch(cmd: ProjectCommand) -> None:
        match cmd:
            case AddProcess(process_name=name):
                ...
            case ConnectWire(source=src, target=tgt):
                ...

Дискриминатор command_type зарезервирован для сериализации в Phase F.
Не является полем dataclass — хранится в ClassVar для экономии памяти (slots=True).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Union

from multiprocess_prototype.domain.entities.plugin import PluginInstance
from multiprocess_prototype.domain.entities.topology import Topology

# ==============================================================================
# Process-команды
# ==============================================================================


@dataclass(frozen=True, slots=True)
class AddProcess:
    """Добавить новый Process в топологию."""

    command_type: ClassVar[str] = "AddProcess"

    process_name: str
    plugins: tuple[PluginInstance, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RemoveProcess:
    """Удалить Process из топологии (каскад: wires + displays)."""

    command_type: ClassVar[str] = "RemoveProcess"

    process_name: str


@dataclass(frozen=True, slots=True)
class RenameProcess:
    """Переименовать Process в топологии."""

    command_type: ClassVar[str] = "RenameProcess"

    old_name: str
    new_name: str


# ==============================================================================
# Plugin-команды
# ==============================================================================


@dataclass(frozen=True, slots=True)
class InsertPlugin:
    """Вставить PluginInstance в цепочку плагинов Process.

    index=None означает добавление в конец (append).
    """

    command_type: ClassVar[str] = "InsertPlugin"

    process_name: str
    plugin: PluginInstance
    index: int | None = None


@dataclass(frozen=True, slots=True)
class RemovePlugin:
    """Удалить PluginInstance из цепочки плагинов Process по индексу."""

    command_type: ClassVar[str] = "RemovePlugin"

    process_name: str
    index: int


@dataclass(frozen=True, slots=True)
class SetPluginConfig:
    """Установить значение поля конфигурации PluginInstance."""

    command_type: ClassVar[str] = "SetPluginConfig"

    process_name: str
    plugin_index: int
    field: str
    value: Any


# ==============================================================================
# Wire-команды
# ==============================================================================


@dataclass(frozen=True, slots=True)
class ConnectWire:
    """Добавить Wire между двумя узлами топологии."""

    command_type: ClassVar[str] = "ConnectWire"

    source: str
    target: str
    src_dtype: str | None = None
    tgt_dtype: str | None = None


@dataclass(frozen=True, slots=True)
class DisconnectWire:
    """Удалить Wire между двумя узлами топологии."""

    command_type: ClassVar[str] = "DisconnectWire"

    source: str
    target: str


# ==============================================================================
# Display-команды
# ==============================================================================


@dataclass(frozen=True, slots=True)
class BindDisplay:
    """Привязать DisplayInstance к узлу топологии."""

    command_type: ClassVar[str] = "BindDisplay"

    node_id: str
    display_id: str


@dataclass(frozen=True, slots=True)
class UnbindDisplay:
    """Отвязать DisplayInstance от узла топологии."""

    command_type: ClassVar[str] = "UnbindDisplay"

    node_id: str


# ==============================================================================
# Target / Recipe / Topology-команды
# ==============================================================================


@dataclass(frozen=True, slots=True)
class AssignTargetProcess:
    """Назначить или сбросить целевой процесс (target_process) для Process.

    target=None сбрасывает привязку.
    """

    command_type: ClassVar[str] = "AssignTargetProcess"

    process_name: str
    target: str | None


@dataclass(frozen=True, slots=True)
class ActivateRecipe:
    """Активировать Recipe по slug."""

    command_type: ClassVar[str] = "ActivateRecipe"

    slug: str


@dataclass(frozen=True, slots=True)
class DeactivateRecipe:
    """Сбросить активный Recipe (нет активного рецепта)."""

    command_type: ClassVar[str] = "DeactivateRecipe"


@dataclass(frozen=True, slots=True)
class ReplaceTopology:
    """Заменить топологию целиком (fallback для recipe launch / blueprint reload).

    topology — уже построенный Topology entity (прошёл model_validate при from_dict).
    reason — строка для диагностики и аудита.
    """

    command_type: ClassVar[str] = "ReplaceTopology"

    topology: Topology
    reason: str


# ==============================================================================
# Discriminated union всех 14 команд
# ==============================================================================

ProjectCommand = Union[
    AddProcess,
    RemoveProcess,
    RenameProcess,
    InsertPlugin,
    RemovePlugin,
    SetPluginConfig,
    ConnectWire,
    DisconnectWire,
    BindDisplay,
    UnbindDisplay,
    AssignTargetProcess,
    ActivateRecipe,
    DeactivateRecipe,
    ReplaceTopology,
]

__all__ = [
    # Конкретные команды
    "AddProcess",
    "RemoveProcess",
    "RenameProcess",
    "InsertPlugin",
    "RemovePlugin",
    "SetPluginConfig",
    "ConnectWire",
    "DisconnectWire",
    "BindDisplay",
    "UnbindDisplay",
    "AssignTargetProcess",
    "ActivateRecipe",
    "DeactivateRecipe",
    "ReplaceTopology",
    # Union-тип
    "ProjectCommand",
]
