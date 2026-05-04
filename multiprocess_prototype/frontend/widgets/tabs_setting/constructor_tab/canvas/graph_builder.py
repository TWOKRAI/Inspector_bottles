"""GraphBuilder — построение NodeGraphQt сцены из topology данных.

Читает процессы и wires из CrossProcessModel / SystemTopologyEditor
и создаёт PluginProcessNode + wire-соединения на канвасе.

Используется при:
- Начальной загрузке вкладки
- Load Blueprint
- Refresh после изменений в Tab «Процессы»
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .auto_layout import auto_layout
from .plugin_process_node import PROCESS_NODE_TYPE, PluginProcessNode

if TYPE_CHECKING:
    from NodeGraphQt import NodeGraph

    from multiprocess_prototype.frontend.models.wire_model import WireEditorModel
    from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.models.cross_process_model import (
        CrossProcessModel,
        ProcessNodeData,
    )

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Строит NodeGraphQt сцену из данных topology.

    Не хранит состояние — stateless builder. Вызывается адаптером
    при загрузке или обновлении данных.
    """

    def __init__(self, graph: NodeGraph) -> None:
        self._graph = graph

    def build(
        self,
        cross_model: CrossProcessModel,
        wires: dict[str, dict],
    ) -> tuple[dict[str, PluginProcessNode], dict[tuple[str, str], str]]:
        """Построить полную сцену: ноды + wire-соединения + layout.

        Args:
            cross_model: Агрегатор данных процессов.
            wires: wire_key → wire dict из WiresSectionView.

        Returns:
            Кортеж (node_map, addr_to_wire_key):
            - node_map: process_key → созданная PluginProcessNode
            - addr_to_wire_key: (source_addr, target_addr) → wire_key
        """
        # Фаза 1: создать ноды
        node_map = self._create_nodes(cross_model)

        # Фаза 2: применить auto-layout
        positions = auto_layout(
            process_keys=set(node_map.keys()),
            wires=wires,
        )
        for pk, (x, y) in positions.items():
            qt_node = node_map.get(pk)
            if qt_node is not None:
                qt_node.set_pos(x, y)

        # Фаза 3: создать wire-соединения, получить маппинг адресов → wire_key
        addr_to_wire_key = self._create_wire_connections(node_map, wires)

        logger.info(
            "GraphBuilder: построена сцена — %d нод, %d wires",
            len(node_map),
            len(wires),
        )
        return node_map, addr_to_wire_key

    def _create_nodes(
        self,
        cross_model: CrossProcessModel,
    ) -> dict[str, PluginProcessNode]:
        """Создать PluginProcessNode для каждого процесса.

        Returns:
            Маппинг process_key → PluginProcessNode.
        """
        node_map: dict[str, PluginProcessNode] = {}

        for pk, node_data in cross_model.process_nodes.items():
            try:
                qt_node = self._graph.create_node(
                    PROCESS_NODE_TYPE,
                    name=node_data.name,
                    selected=False,
                    push_undo=False,
                )
            except Exception as exc:
                logger.error(
                    "GraphBuilder: ошибка создания ноды '%s': %s", pk, exc,
                )
                continue

            if not isinstance(qt_node, PluginProcessNode):
                logger.warning(
                    "GraphBuilder: нода '%s' не PluginProcessNode", pk,
                )
                continue

            # Установить данные процесса (плагины, приоритет)
            qt_node.set_process_data(
                process_key=pk,
                plugin_names=node_data.plugin_names,
                priority=node_data.priority,
            )

            # Создать входные порты (от первого плагина цепочки)
            for port_info in node_data.input_ports:
                qt_node.add_input(
                    name=f"{port_info.plugin_name}.{port_info.name}",
                    multi_input=False,
                )

            # Создать выходные порты (от последнего плагина цепочки)
            for port_info in node_data.output_ports:
                qt_node.add_output(
                    name=f"{port_info.plugin_name}.{port_info.name}",
                    multi_output=True,
                )

            node_map[pk] = qt_node

        return node_map

    def _create_wire_connections(
        self,
        node_map: dict[str, PluginProcessNode],
        wires: dict[str, dict],
    ) -> dict[tuple[str, str], str]:
        """Создать визуальные соединения (edges) из wire-данных.

        Wire source/target формат: "process.plugin.port"
        Port name в NodeGraphQt: "plugin.port"

        Returns:
            Маппинг (source_addr, target_addr) → wire_key для всех
            успешно созданных соединений.
        """
        # Маппинг: (source_addr, target_addr) → wire_key
        addr_to_wire_key: dict[tuple[str, str], str] = {}

        for wk, wire in wires.items():
            source_addr = wire.get("source", "")
            target_addr = wire.get("target", "")

            src_parts = source_addr.split(".")
            tgt_parts = target_addr.split(".")

            if len(src_parts) != 3 or len(tgt_parts) != 3:
                logger.warning(
                    "GraphBuilder: wire '%s' — некорректный формат адресов", wk,
                )
                continue

            src_proc, src_plugin, src_port = src_parts
            tgt_proc, tgt_plugin, tgt_port = tgt_parts

            src_node = node_map.get(src_proc)
            tgt_node = node_map.get(tgt_proc)

            if src_node is None or tgt_node is None:
                logger.warning(
                    "GraphBuilder: wire '%s' — процесс не найден на канвасе "
                    "(src=%s, tgt=%s)",
                    wk, src_proc, tgt_proc,
                )
                continue

            # Имена портов на ноде: "plugin_name.port_name"
            out_port_name = f"{src_plugin}.{src_port}"
            in_port_name = f"{tgt_plugin}.{tgt_port}"

            out_port = src_node.get_output(out_port_name)
            in_port = tgt_node.get_input(in_port_name)

            if out_port is None or in_port is None:
                logger.warning(
                    "GraphBuilder: wire '%s' — порт не найден "
                    "(out='%s', in='%s')",
                    wk, out_port_name, in_port_name,
                )
                continue

            try:
                out_port.connect_to(in_port, push_undo=False)
                # Записать маппинг только для успешных соединений
                addr_to_wire_key[(source_addr, target_addr)] = wk
            except Exception as exc:
                logger.warning(
                    "GraphBuilder: wire '%s' — ошибка соединения: %s",
                    wk, exc,
                )

        return addr_to_wire_key

    def clear(self) -> None:
        """Очистить канвас (удалить все ноды)."""
        all_nodes = self._graph.all_nodes()
        for node in list(all_nodes):
            try:
                self._graph.delete_node(node, push_undo=False)
            except Exception:
                pass


__all__ = ["GraphBuilder"]
