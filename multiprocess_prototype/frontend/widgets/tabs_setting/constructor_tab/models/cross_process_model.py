"""CrossProcessModel — агрегатор данных процессов для канваса конструктора.

Читает из SystemTopologyEditor (единое дерево данных) и предоставляет
удобный API для canvas-компонентов: список процессов с их плагинами,
входные/выходные порты каждого процесса (порты первого и последнего плагина).

Без Qt-зависимостей — чистая бизнес-логика.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import (
        SystemTopologyEditor,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortInfo:
    """Описание порта плагина для отображения на ноде."""

    name: str
    plugin_name: str
    data_type: str = "any"
    direction: str = "output"  # "input" | "output"

    @property
    def address(self) -> str:
        """Полный адрес: будет дополнен process_key при использовании."""
        return f"{self.plugin_name}.{self.name}"


@dataclass
class ProcessNodeData:
    """Данные процесса для отображения как ноды на канвасе.

    Содержит всё, что нужно для создания PluginProcessNode:
    - ключ и имя процесса
    - список плагинов (имена)
    - входные порты (от первого плагина цепочки)
    - выходные порты (от последнего плагина цепочки)
    """

    process_key: str
    name: str
    class_path: str = ""
    priority: str = "normal"
    plugin_names: list[str] = field(default_factory=list)
    input_ports: list[PortInfo] = field(default_factory=list)
    output_ports: list[PortInfo] = field(default_factory=list)
    position: tuple[float, float] | None = None


def _get_registry():
    """Lazy-импорт PluginRegistry с graceful degradation."""
    try:
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
        )
        return PluginRegistry
    except ImportError:
        return None


class CrossProcessModel:
    """Агрегатор данных процессов для канваса конструктора.

    Читает из SystemTopologyEditor и формирует список ProcessNodeData
    для отображения на NodeGraphQt канвасе.

    Подписывается на изменения секций processes и wires — при изменении
    процессов или плагинов канвас получает обновлённые данные.
    """

    def __init__(self, editor: SystemTopologyEditor) -> None:
        self._editor = editor
        # Кэш: process_key → ProcessNodeData
        self._cache: dict[str, ProcessNodeData] = {}
        self._dirty = True

    def invalidate(self) -> None:
        """Пометить кэш как устаревший (вызывать при изменении processes)."""
        self._dirty = True

    @property
    def process_nodes(self) -> dict[str, ProcessNodeData]:
        """Все процессы с их плагинами и портами.

        Кэшируется до следующего invalidate().
        """
        if self._dirty:
            self._rebuild()
        return dict(self._cache)

    def get_node(self, process_key: str) -> ProcessNodeData | None:
        """Данные конкретного процесса."""
        if self._dirty:
            self._rebuild()
        return self._cache.get(process_key)

    def port_address(self, process_key: str, port: PortInfo) -> str:
        """Полный адрес порта: process.plugin.port."""
        return f"{process_key}.{port.address}"

    def _rebuild(self) -> None:
        """Перестроить кэш из текущего состояния topology editor."""
        self._cache.clear()
        processes: dict[str, dict] = self._editor._data.get("processes", {})
        registry = _get_registry()

        for proc_key, proc_data in processes.items():
            plugin_names = [
                p.get("plugin_name", "") for p in proc_data.get("plugins", [])
            ]

            input_ports = self._resolve_ports(
                proc_data.get("plugins", []), registry, direction="input",
            )
            output_ports = self._resolve_ports(
                proc_data.get("plugins", []), registry, direction="output",
            )

            self._cache[proc_key] = ProcessNodeData(
                process_key=proc_key,
                name=proc_data.get("name", proc_key),
                class_path=proc_data.get("class_path", ""),
                priority=proc_data.get("priority", "normal"),
                plugin_names=plugin_names,
                input_ports=input_ports,
                output_ports=output_ports,
            )

        self._dirty = False
        logger.debug(
            "CrossProcessModel: перестроен кэш — %d процессов",
            len(self._cache),
        )

    @staticmethod
    def _resolve_ports(
        plugins: list[dict[str, Any]],
        registry: Any,
        direction: str,
    ) -> list[PortInfo]:
        """Извлечь порты из цепочки плагинов.

        Для input — берём входы первого плагина.
        Для output — берём выходы последнего плагина.
        Graceful degradation: если registry недоступен, возвращаем пустой список.
        """
        if not plugins or registry is None:
            return []

        if direction == "input":
            plugin_dict = plugins[0]
        else:
            plugin_dict = plugins[-1]

        plugin_name = plugin_dict.get("plugin_name", "")
        if not plugin_name:
            return []

        entry = registry.get(plugin_name)
        if entry is None:
            return []

        port_list = entry.inputs if direction == "input" else entry.outputs
        return [
            PortInfo(
                name=p.name,
                plugin_name=plugin_name,
                data_type=getattr(p, "dtype", "any"),
                direction=direction,
            )
            for p in port_list
        ]


__all__ = ["CrossProcessModel", "ProcessNodeData", "PortInfo"]
