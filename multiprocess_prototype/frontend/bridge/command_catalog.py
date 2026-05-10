"""CommandCatalog — каталог доступных IPC-команд из PluginRegistry.

Агрегирует plugin.commands со всех плагинов + ConnectionMap (plugin → process).
Предоставляет resolve: (plugin_name, field_name) → ResolvedCommand.

Это модульный блок конструктора — pure Python, без Qt, независимо тестируемый.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# --- Протоколы (интерфейсы для DI) ---


@runtime_checkable
class IPluginRegistry(Protocol):
    """Минимальный интерфейс PluginRegistry для CommandCatalog."""

    def list(self) -> list[Any]: ...
    def get(self, name: str) -> Any | None: ...


@runtime_checkable
class IConnectionMap(Protocol):
    """Минимальный интерфейс ConnectionMap для CommandCatalog."""

    def get_process(self, plugin_name: str) -> str | None: ...
    def plugins(self) -> list[str]: ...


# --- Результаты ---


@dataclass(frozen=True)
class ResolvedCommand:
    """Результат resolve — куда и какую команду отправить."""

    process_name: str
    command_name: str
    plugin_name: str


@dataclass
class PluginCommands:
    """Набор команд одного плагина."""

    plugin_name: str
    process_name: str
    category: str
    commands: dict[str, str] = field(default_factory=dict)
    register_fields: list[str] = field(default_factory=list)

    @property
    def has_commands(self) -> bool:
        return bool(self.commands)


# --- Каталог ---


class CommandCatalog:
    """Каталог IPC-команд, собранный из PluginRegistry + ConnectionMap.

    Два способа создания:
    1. from_registry_and_map(registry, connection_map) — из готовых объектов
    2. from_topology(registry, topology_dict) — строит ConnectionMap внутри

    Resolve-логика для field_set:
    - Если plugin.commands содержит "set_{field_name}" → вернуть его
    - Иначе если commands не пуст → convention "set_config" с полем в args
    - Если commands пуст → None (stateless плагин, IPC не нужен)
    """

    def __init__(self, entries: dict[str, PluginCommands] | None = None) -> None:
        self._entries: dict[str, PluginCommands] = dict(entries or {})

    @classmethod
    def from_registry_and_map(
        cls,
        registry: IPluginRegistry,
        connection_map: IConnectionMap,
    ) -> CommandCatalog:
        """Построить каталог из PluginRegistry + ConnectionMap.

        Args:
            registry: Каталог плагинов (PluginEntry с plugin_class.commands).
            connection_map: Маппинг plugin → process из topology.
        """
        entries: dict[str, PluginCommands] = {}

        for entry in registry.list():
            name = entry.name
            process_name = connection_map.get_process(name)
            if process_name is None:
                # Плагин есть в registry, но не в topology — пропускаем
                continue

            # Получаем commands dict с класса плагина
            plugin_cls = entry.plugin_class
            commands: dict[str, str] = dict(getattr(plugin_cls, "commands", {}) or {})

            # Получаем имена полей из register_classes
            register_fields: list[str] = []
            for rc in getattr(entry, "register_classes", []):
                if rc is not None:
                    for field_name in getattr(rc, "model_fields", {}):
                        register_fields.append(field_name)

            entries[name] = PluginCommands(
                plugin_name=name,
                process_name=process_name,
                category=getattr(entry, "category", ""),
                commands=commands,
                register_fields=register_fields,
            )

        return cls(entries)

    @classmethod
    def from_topology(
        cls,
        registry: IPluginRegistry,
        topology: dict[str, Any],
    ) -> CommandCatalog:
        """Построить каталог из PluginRegistry + topology dict.

        Создаёт ConnectionMap внутри — удобный shortcut.
        """
        from ...registers.connection_map import ConnectionMap

        cmap = ConnectionMap.from_topology(topology)
        return cls.from_registry_and_map(registry, cmap)

    # --- Resolve ---

    def resolve_field_command(
        self,
        plugin_name: str,
        field_name: str,
    ) -> ResolvedCommand | None:
        """Определить команду для изменения поля плагина.

        Логика:
        1. Плагин не найден → None
        2. commands пуст → None (stateless, IPC не нужен)
        3. commands содержит "set_{field_name}" → вернуть
        4. Иначе → convention "set_config" (generic setter)

        Returns:
            ResolvedCommand или None если команда не нужна.
        """
        pc = self._entries.get(plugin_name)
        if pc is None:
            return None

        if not pc.has_commands:
            return None

        # Точное совпадение: set_{field_name}
        exact = f"set_{field_name}"
        if exact in pc.commands:
            return ResolvedCommand(
                process_name=pc.process_name,
                command_name=exact,
                plugin_name=plugin_name,
            )

        # Convention: generic set_config
        if pc.has_commands:
            return ResolvedCommand(
                process_name=pc.process_name,
                command_name="set_config",
                plugin_name=plugin_name,
            )

        return None  # pragma: no cover

    def resolve_action_command(
        self,
        plugin_name: str,
        command_name: str,
    ) -> ResolvedCommand | None:
        """Определить команду для явного действия (start/stop и т.п.).

        Returns:
            ResolvedCommand или None если команда не найдена.
        """
        pc = self._entries.get(plugin_name)
        if pc is None:
            return None

        if command_name not in pc.commands:
            return None

        return ResolvedCommand(
            process_name=pc.process_name,
            command_name=command_name,
            plugin_name=plugin_name,
        )

    # --- Инспекция ---

    def get_plugin(self, plugin_name: str) -> PluginCommands | None:
        """Получить PluginCommands по имени."""
        return self._entries.get(plugin_name)

    def list_commands(self, plugin_name: str) -> list[str]:
        """Все имена команд плагина."""
        pc = self._entries.get(plugin_name)
        if pc is None:
            return []
        return list(pc.commands.keys())

    def all_plugins(self) -> list[str]:
        """Все плагины в каталоге."""
        return list(self._entries.keys())

    def plugins_with_commands(self) -> list[str]:
        """Плагины, у которых есть команды (не stateless)."""
        return [name for name, pc in self._entries.items() if pc.has_commands]

    def plugins_without_commands(self) -> list[str]:
        """Stateless плагины (commands пуст)."""
        return [name for name, pc in self._entries.items() if not pc.has_commands]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, plugin_name: str) -> bool:
        return plugin_name in self._entries
