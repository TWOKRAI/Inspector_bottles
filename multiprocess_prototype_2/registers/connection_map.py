"""ConnectionMap — маппинг (plugin_name, field_name) → (process_name, command, arg_key).

Строится из topology YAML: для каждого process → каждого plugin → запоминает
в каком процессе запущен плагин. При GUI-изменении параметра ConnectionMap
определяет куда отправить IPC-команду.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolvedTarget:
    """Результат resolve() — куда отправить команду при изменении поля."""

    process_name: str
    command_name: str
    arg_key: str


class ConnectionMap:
    """Маппинг plugin → process из topology YAML.

    Topology:
        processes:
          - process_name: "camera_0"
            plugins:
              - plugin_name: "capture"
                ...
          - process_name: "processor_0"
            plugins:
              - plugin_name: "color_mask"
                ...

    Результат:
        ConnectionMap._map = {"capture": "camera_0", "color_mask": "processor_0"}
    """

    def __init__(self, plugin_to_process: dict[str, str] | None = None) -> None:
        self._map: dict[str, str] = dict(plugin_to_process or {})

    @classmethod
    def from_topology(cls, topology: dict[str, Any]) -> ConnectionMap:
        """Построить из topology dict.

        Args:
            topology: dict с ключом "processes" → list of process dicts.
                Каждый process dict имеет "process_name" и "plugins" (list of dicts).
        """
        mapping: dict[str, str] = {}

        for proc in topology.get("processes", []):
            process_name = proc.get("process_name", "")
            if not process_name:
                continue
            for plugin_dict in proc.get("plugins", []):
                plugin_name = plugin_dict.get("plugin_name", "")
                if plugin_name:
                    mapping[plugin_name] = process_name

        return cls(plugin_to_process=mapping)

    def resolve(
        self,
        plugin_name: str,
        field_name: str,
    ) -> ResolvedTarget | None:
        """Определить куда отправить команду при изменении поля.

        Convention: command_name = "set_{field_name}", arg_key = field_name.
        Плагин может override через свой commands dict (Phase 12).

        Args:
            plugin_name: Имя плагина.
            field_name: Имя поля регистра.

        Returns:
            ResolvedTarget или None если плагин не найден в topology.
        """
        process_name = self._map.get(plugin_name)
        if process_name is None:
            return None

        return ResolvedTarget(
            process_name=process_name,
            command_name=f"set_{field_name}",
            arg_key=field_name,
        )

    def get_process(self, plugin_name: str) -> str | None:
        """В каком процессе запущен плагин."""
        return self._map.get(plugin_name)

    def plugins(self) -> list[str]:
        """Все плагины в маппинге."""
        return list(self._map.keys())

    def processes(self) -> list[str]:
        """Все уникальные процессы."""
        return list(set(self._map.values()))

    def plugins_in_process(self, process_name: str) -> list[str]:
        """Все плагины в указанном процессе."""
        return [p for p, proc in self._map.items() if proc == process_name]

    def to_dict(self) -> dict[str, str]:
        """Экспорт для FW RegistersManager.connection_map."""
        return dict(self._map)
