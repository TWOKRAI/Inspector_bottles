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
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .auto_layout import auto_layout
from .display_target_node import DISPLAY_NODE_TYPE, DisplayTargetNode
from .plugin_process_node import PROCESS_NODE_TYPE, PluginProcessNode
from .shm_route_node import ROUTE_NODE_TYPE, ShmRouteNode

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
        displays_data: dict[str, dict] | None = None,
    ) -> tuple[
        dict[str, PluginProcessNode],
        dict[tuple[str, str], str],
        dict[str, ShmRouteNode],
        dict[str, DisplayTargetNode],
    ]:
        """Построить полную сцену: ноды + wire-соединения + route nodes + display nodes + layout.

        Args:
            cross_model: Агрегатор данных процессов.
            wires: wire_key → wire dict из WiresSectionView.
            displays_data: display_key → display dict из секции displays.
                Если None или пустой — display-ноды не создаются.

        Returns:
            Кортеж (node_map, addr_to_wire_key, route_nodes, display_nodes):
            - node_map: process_key → созданная PluginProcessNode
            - addr_to_wire_key: (source_addr, target_addr) → wire_key
            - route_nodes: source_addr → ShmRouteNode (fan-out >= 2)
            - display_nodes: display_key → DisplayTargetNode
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

        # Фаза 4: вставить route nodes для fan-out >= 2
        route_nodes = self._insert_route_nodes(node_map, wires, addr_to_wire_key)

        # Фаза 5: создать display-ноды из секции displays
        display_nodes = self._create_display_nodes(node_map, displays_data)

        logger.info(
            "GraphBuilder: построена сцена — %d нод, %d wires, %d route nodes, "
            "%d display nodes",
            len(node_map),
            len(wires),
            len(route_nodes),
            len(display_nodes),
        )
        return node_map, addr_to_wire_key, route_nodes, display_nodes

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

    def _create_display_nodes(
        self,
        node_map: dict[str, PluginProcessNode],
        displays_data: dict[str, dict] | None,
    ) -> dict[str, DisplayTargetNode]:
        """Создать DisplayTargetNode для каждого display из topology.

        Display-ноды позиционируются правее всех process-нод.

        Args:
            node_map: process_key → PluginProcessNode (для вычисления позиций).
            displays_data: display_key → display dict (name, source_ref, fps_limit).

        Returns:
            Маппинг display_key → DisplayTargetNode.
        """
        if not displays_data:
            return {}

        display_nodes: dict[str, DisplayTargetNode] = {}

        # Вычислить max_x среди process-нод для позиционирования display-нод правее
        max_x = 0.0
        for qt_node in node_map.values():
            x = qt_node.x_pos()
            if x > max_x:
                max_x = x

        display_x = max_x + 300.0

        for idx, (display_key, display_data) in enumerate(displays_data.items()):
            display_name = display_data.get("name", display_key)

            try:
                qt_node = self._graph.create_node(
                    DISPLAY_NODE_TYPE,
                    name=display_name,
                    selected=False,
                    push_undo=False,
                )
            except Exception as exc:
                logger.error(
                    "GraphBuilder: ошибка создания display-ноды '%s': %s",
                    display_key, exc,
                )
                continue

            if not isinstance(qt_node, DisplayTargetNode):
                logger.warning(
                    "GraphBuilder: нода '%s' не DisplayTargetNode", display_key,
                )
                continue

            fps_limit = display_data.get("fps_limit", 30)
            qt_node.set_display_data(display_key, display_name, fps_limit)

            # Позиционирование: правее process-нод, вертикально по порядку
            display_y = idx * 120.0
            qt_node.set_pos(display_x, display_y)

            display_nodes[display_key] = qt_node

        return display_nodes

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

    # ------------------------------------------------------------------
    # Fan-out route nodes
    # ------------------------------------------------------------------

    def _insert_route_nodes(
        self,
        node_map: dict[str, PluginProcessNode],
        wires: dict[str, dict],
        addr_to_wire_key: dict[tuple[str, str], str],
    ) -> dict[str, ShmRouteNode]:
        """Создать ShmRouteNode для каждого source_addr с fan-out >= 2.

        Route node — чисто визуальный элемент: перехватывает pipes
        (source → targets) и пропускает через себя. Wire model не меняется.

        Алгоритм:
        1. Сгруппировать wires по source_addr
        2. Для fan-out >= 2: создать ShmRouteNode, переключить pipes

        Args:
            node_map: process_key → PluginProcessNode.
            wires: wire_key → wire dict.
            addr_to_wire_key: (source_addr, target_addr) → wire_key.

        Returns:
            source_addr → ShmRouteNode.
        """
        # Сгруппировать target_addr по source_addr
        fan_out_groups: dict[str, list[str]] = defaultdict(list)
        for (src_addr, tgt_addr) in addr_to_wire_key:
            fan_out_groups[src_addr].append(tgt_addr)

        route_nodes: dict[str, ShmRouteNode] = {}

        for source_addr, targets in fan_out_groups.items():
            if len(targets) < 2:
                continue

            # Разобрать адрес источника
            src_parts = source_addr.split(".")
            if len(src_parts) != 3:
                continue

            src_proc, src_plugin, src_port = src_parts
            src_node = node_map.get(src_proc)
            if src_node is None:
                continue

            out_port_name = f"{src_plugin}.{src_port}"
            out_port = src_node.get_output(out_port_name)
            if out_port is None:
                continue

            # Собрать целевые порты
            target_ports = []
            for tgt_addr in targets:
                tgt_parts = tgt_addr.split(".")
                if len(tgt_parts) != 3:
                    continue
                tgt_proc, tgt_plugin, tgt_port = tgt_parts
                tgt_node = node_map.get(tgt_proc)
                if tgt_node is None:
                    continue
                in_port = tgt_node.get_input(f"{tgt_plugin}.{tgt_port}")
                if in_port is not None:
                    target_ports.append(in_port)

            if len(target_ports) < 2:
                continue

            # Удалить прямые pipes (source → targets)
            for tp in target_ports:
                try:
                    out_port.disconnect_from(tp, push_undo=False)
                except Exception:
                    pass

            # Создать route node
            shm_name = self._make_shm_name(source_addr)
            try:
                route_node = self._graph.create_node(
                    ROUTE_NODE_TYPE,
                    name=f"Route: {shm_name}",
                    selected=False,
                    push_undo=False,
                )
            except Exception as exc:
                logger.error(
                    "GraphBuilder: ошибка создания route node для '%s': %s",
                    source_addr, exc,
                )
                # Восстановить прямые pipes
                for tp in target_ports:
                    try:
                        out_port.connect_to(tp, push_undo=False)
                    except Exception:
                        pass
                continue

            if not isinstance(route_node, ShmRouteNode):
                logger.warning(
                    "GraphBuilder: route node не ShmRouteNode для '%s'",
                    source_addr,
                )
                continue

            route_node.set_route_data(source_addr, shm_name, len(target_ports))

            # Позиция: среднее между source и средним targets
            src_x, src_y = src_node.x_pos(), src_node.y_pos()
            tgt_xs = [tp.node().x_pos() for tp in target_ports]
            tgt_ys = [tp.node().y_pos() for tp in target_ports]
            avg_tgt_x = sum(tgt_xs) / len(tgt_xs)
            avg_tgt_y = sum(tgt_ys) / len(tgt_ys)
            route_x = (src_x + avg_tgt_x) / 2.0
            route_y = avg_tgt_y
            route_node.set_pos(route_x, route_y)

            # Подключить: source → route.in
            route_in = route_node.get_input("in")
            if route_in is not None:
                try:
                    out_port.connect_to(route_in, push_undo=False)
                except Exception as exc:
                    logger.warning(
                        "GraphBuilder: route source→in ошибка: %s", exc,
                    )

            # Подключить: route.out_N → target
            for i, tp in enumerate(target_ports):
                route_out = route_node.get_output(f"out_{i + 1}")
                if route_out is not None:
                    try:
                        route_out.connect_to(tp, push_undo=False)
                    except Exception as exc:
                        logger.warning(
                            "GraphBuilder: route out_%d→target ошибка: %s",
                            i + 1, exc,
                        )

            route_nodes[source_addr] = route_node
            logger.debug(
                "GraphBuilder: route node для '%s' — %d выходов",
                source_addr, len(target_ports),
            )

        return route_nodes

    @staticmethod
    def _make_shm_name(source_addr: str) -> str:
        """Конвертировать source_addr в имя SHM.

        Формат: "process.plugin.port" → "process__plugin__port"
        """
        return source_addr.replace(".", "__")

    def clear(self) -> None:
        """Очистить канвас (удалить все ноды)."""
        all_nodes = self._graph.all_nodes()
        for node in list(all_nodes):
            try:
                self._graph.delete_node(node, push_undo=False)
            except Exception:
                pass


__all__ = ["GraphBuilder"]
