# -*- coding: utf-8 -*-
"""Codec топология-dict → граф-структуры (Трек F, Task F.2).

Чистое (Qt-free) преобразование топологии в ``NodeData``/``EdgeData``/
``DisplayNodeData``/``PortSchema``. Вынесено из ``PipelinePresenter`` дословно —
наблюдаемое поведение заморожено характеризационными тестами
(``tests/test_graph_codec_characterization.py``, F.1) и НЕ меняется этим разрезом.

Разграничение ответственности:
- владелец GUI-состояния (позиции нод, локи, размещённые-но-непривязанные боксы)
  остаётся ``PipelinePresenter`` и передаётся в codec снимком :class:`GraphViewState`;
- кэши портов и display-боксов возвращаются в :class:`GraphBuildResult` (presenter
  кладёт их в свои поля ``_port_schemas_cache``/``_display_nodes_cache``), а не
  пишутся в поля codec — так codec остаётся без состояния между вызовами.

``D.1``: нода = плагин. Один процесс → N плагин-нод (``{proc}.{plugin}``) + неявные
стрелки цепочки между соседними плагинами. Процесс без плагинов рендерится одной
process-fallback нодой (``node_id=process_name``, ``plugin_index=-1``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import AbstractSet, Any, Mapping

from .graph.data import DisplayNodeData, EdgeData, NodeData, PortSchema

logger = logging.getLogger(__name__)


# Ключевой config-параметр в подписи ноды: {plugin_name: (config_key, префикс)}.
_NODE_SUBTITLE_PARAM: dict[str, tuple[str, str]] = {
    "color_convert": ("mode", ""),
    "hikvision": ("camera_id", "id "),
}


def _plugin_config_value(pl: Any, key: str) -> Any:
    """Значение config-параметра плагина (поддержка плоского и вложенного config)."""
    if isinstance(pl, dict):
        if key in pl:
            return pl[key]
        cfg = pl.get("config")
        return cfg.get(key) if isinstance(cfg, dict) else None
    if hasattr(pl, key):
        return getattr(pl, key)
    cfg = getattr(pl, "config", None)
    return cfg.get(key) if isinstance(cfg, dict) else None


def _node_subtitle(category: str, plugin_name: str, pl: Any) -> str:
    """Подпись ноды: 'category · <param>' если у плагина есть ключевой параметр."""
    spec = _NODE_SUBTITLE_PARAM.get(plugin_name)
    if spec is None:
        return category
    key, prefix = spec
    val = _plugin_config_value(pl, key)
    if val is None or val == "":
        return category
    return f"{category} · {prefix}{val}"


@dataclass(frozen=True)
class GraphViewState:
    """Снимок GUI-состояния presenter'а — вход codec'а (read-only).

    - ``gui_positions`` — позиции нод/боксов (``node_id → (x, y)``);
    - ``locked_nodes`` — зафиксированные ноды (проецируются в ``NodeData.locked``);
    - ``placed_display_ids`` — размещённые, но ещё не привязанные display-боксы
      (их нет в ``topo["displays"]``, но их надо дорисовать при reload).
    """

    gui_positions: Mapping[str, tuple[float, float]]
    locked_nodes: AbstractSet[str]
    placed_display_ids: AbstractSet[str]


@dataclass
class GraphBuildResult:
    """Результат codec'а: граф-данные + кэши, которые presenter кладёт в свои поля."""

    nodes: list[NodeData]
    edges: list[EdgeData]
    display_nodes: list[DisplayNodeData]
    port_schemas: dict[str, list[PortSchema]]


class TopologyGraphCodec:
    """Преобразователь topology dict → граф-структуры (без Qt, без состояния между вызовами).

    Зависимости — ``PluginCatalog`` (``services.plugins``) и ``DisplayCatalog``
    (``services.displays``): категории/порты плагинов и человекочитаемые имена
    каналов дисплеев.
    """

    def __init__(self, plugins: Any, displays: Any) -> None:
        self._plugins = plugins
        self._displays = displays

    # ------------------------------------------------------------------ #
    #  Основной вход                                                       #
    # ------------------------------------------------------------------ #

    def topology_to_graph(self, topo_dict: dict, view: GraphViewState) -> GraphBuildResult:
        """Конвертировать topology dict → NodeData/EdgeData (+ display-боксы, кэш портов).

        D.1: **нода = плагин**. Один процесс → N плагин-нод (node_id=`{proc}.{plugin}`)
        + неявные стрелки цепочки (implicit edges) между соседними плагинами. Процесс
        без плагинов рендерится одной process-fallback нодой (node_id=process_name,
        plugin_index=-1).

        G.4.2: port_schemas реконструируются из ``plugins.resolve()`` ПО КАЖДОМУ
        плагину (не только первому) и складываются в ``GraphBuildResult.port_schemas``
        по node_id плагин-ноды.

        Внешние wires (`proc.plugin.* → proc2.plugin2.*`) мапятся на конкретные
        плагин-ноды (НЕ схлопываются до процесса). Display-боксы — из topo["displays"]
        (binding-ребро source-плагин-нода → бокс).
        """
        nodes: list[NodeData] = []
        edges: list[EdgeData] = []
        port_schemas_map: dict[str, list[PortSchema]] = {}

        processes = topo_dict.get("processes", [])
        used_ids: set[str] = set()  # уникальность node_id (дубликаты plugin_name)

        for pi, proc in enumerate(processes):
            protected = proc.get("protected", False) if isinstance(proc, dict) else getattr(proc, "protected", False)
            if protected:
                # protected-процессы (gui из base.yaml) — фундамент, не рисуем.
                continue

            if isinstance(proc, dict):
                name = proc.get("process_name", "unnamed")
                plugins = proc.get("plugins", [])
            else:
                name = getattr(proc, "process_name", "unnamed")
                plugins = getattr(proc, "plugins", [])

            if not plugins:
                # Процесс без плагинов → одна process-fallback нода (node_id=process).
                x, y = self._node_position(view.gui_positions, name, name, pi, 0)
                nodes.append(
                    NodeData(
                        node_id=name,
                        title=name,
                        subtitle="(пусто)",
                        category="utility",
                        x=x,
                        y=y,
                        process_name=name,
                        plugin_index=-1,
                        plugin_name="",
                        locked=name in view.locked_nodes,
                    )
                )
                used_ids.add(name)
                continue

            prev_node_id: str | None = None
            for j, pl in enumerate(plugins):
                pname = pl.get("plugin_name", "") if isinstance(pl, dict) else getattr(pl, "plugin_name", "")
                category = "utility"
                node_ports: list[PortSchema] | None = None
                if pname:
                    spec = self._plugins.resolve(pname)
                    if spec is not None:
                        category = spec.category
                        try:
                            schemas = [
                                PortSchema(
                                    name=ps.name,
                                    direction=ps.direction,
                                    dtype=ps.dtype,
                                    optional=ps.optional,
                                )
                                for ps in spec.ports
                            ]
                            node_ports = schemas or None
                        except Exception:
                            node_ports = None

                node_id = self._unique_plugin_node_id(name, pname, j, used_ids)
                used_ids.add(node_id)
                if node_ports:
                    port_schemas_map[node_id] = node_ports

                # Подпись ноды: категория + ключевой параметр плагина (если задан).
                subtitle = _node_subtitle(category, pname, pl)

                x, y = self._node_position(view.gui_positions, node_id, name, pi, j)
                nodes.append(
                    NodeData(
                        node_id=node_id,
                        title=pname or name,
                        subtitle=subtitle,
                        category=category,
                        x=x,
                        y=y,
                        process_name=name,
                        plugin_index=j,
                        plugin_name=pname,
                        locked=node_id in view.locked_nodes,
                    )
                )

                # Неявная стрелка цепочки: предыдущий плагин → текущий.
                if prev_node_id is not None:
                    edges.append(EdgeData(source_id=prev_node_id, target_id=node_id, implicit=True))
                prev_node_id = node_id

        # Внешние wires → конкретные плагин-ноды.
        for w in topo_dict.get("wires", []):
            if isinstance(w, dict):
                source = w.get("source", "")
                target = w.get("target", "")
            else:
                source = getattr(w, "source", "")
                target = getattr(w, "target", "")
            if source and target:
                s_node = self._endpoint_to_node_id(source, topo_dict)
                t_node = self._endpoint_to_node_id(target, topo_dict)
                if s_node and t_node:
                    edges.append(EdgeData(source_id=s_node, target_id=t_node))

        # G.4.2b: display-боксы + binding-рёбра из topo["displays"]
        display_nodes = self._build_display_nodes(topo_dict, edges, view)

        return GraphBuildResult(
            nodes=nodes,
            edges=edges,
            display_nodes=display_nodes,
            port_schemas=port_schemas_map,
        )

    # ------------------------------------------------------------------ #
    #  Хелперы node=plugin (D.1)                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _unique_plugin_node_id(process: str, plugin_name: str, index: int, used: set[str]) -> str:
        """node_id плагин-ноды = `{process}.{plugin_name}`.

        Дубликаты plugin_name в одном процессе (против конвенции «1 плагин/процесс»
        и неразличимы в endpoint-схеме domain) получают суффикс `#i` для GUI-
        уникальности. Первое вхождение — без суффикса, чтобы wire-endpoint
        (`proc.plugin`) мапился на него. См. план pipeline-process-container-nodes.
        """
        base = f"{process}.{plugin_name}" if plugin_name else f"{process}.plugin{index}"
        if base not in used:
            return base
        suffixed = f"{base}#{index}"
        logger.warning(
            "Дубликат plugin_name '%s' в процессе '%s' — GUI node_id '%s' (endpoint неразличим)",
            plugin_name,
            process,
            suffixed,
        )
        return suffixed

    @staticmethod
    def _node_position(
        gui_positions: Mapping[str, tuple[float, float]],
        node_id: str,
        process_name: str,
        process_index: int,
        plugin_index: int,
    ) -> tuple[float, float]:
        """Позиция плагин-ноды: из gui_positions или дефолтный кластер по процессу.

        Приоритет: (1) позиция самой плагин-ноды (`proc.plugin`) — обычный путь
        после auto_layout/сохранения; (2) anchor процесса в gui_positions —
        legacy-рецепты и add_process_from_plugin кладут позицию по имени процесса,
        плагин 0 встаёт в anchor, остальные смещаются вправо; (3) дефолтный
        кластер (процесс=колонка). auto_layout_scene переразложит группами.
        """
        from .graph.constants import CONTAINER_HEADER_H, CONTAINER_INNER_GAP, CONTAINER_PADDING, NODE_WIDTH

        if node_id in gui_positions:
            return gui_positions[node_id]
        if process_name in gui_positions:
            base_x, base_y = gui_positions[process_name]
        else:
            base_x = 60.0 + process_index * 340.0
            base_y = 60.0 + CONTAINER_HEADER_H + CONTAINER_PADDING
        x = base_x + plugin_index * (NODE_WIDTH + CONTAINER_INNER_GAP)
        return x, base_y

    @staticmethod
    def _endpoint_to_node_id(endpoint: str, topo_dict: dict) -> str:
        """endpoint `proc.plugin.port` → node_id плагин-ноды (`proc.plugin`).

        Процесс без плагинов → node_id = process (process-fallback нода). При
        отсутствии plugin-сегмента берётся первый плагин процесса.
        """
        parts = endpoint.split(".")
        proc = parts[0]
        # Найти процесс и его плагины.
        plugins: list = []
        for p in topo_dict.get("processes", []):
            pn = p.get("process_name", "") if isinstance(p, dict) else getattr(p, "process_name", "")
            if pn == proc:
                plugins = p.get("plugins", []) if isinstance(p, dict) else getattr(p, "plugins", [])
                break
        if not plugins:
            return proc
        if len(parts) >= 2:
            return f"{proc}.{parts[1]}"
        first = plugins[0]
        first_name = first.get("plugin_name", "") if isinstance(first, dict) else getattr(first, "plugin_name", "")
        return f"{proc}.{first_name}" if first_name else proc

    def _build_display_nodes(
        self,
        topo_dict: dict,
        edges: list[EdgeData],
        view: GraphViewState,
    ) -> list[DisplayNodeData]:
        """Построить display-боксы и binding-рёбра из topo["displays"] (G.4.2b).

        Binding-формат: {node_id: <source endpoint>, display_id, display_name?}.
        Один бокс на display_id (fan-in: N источников → 1 бокс), binding-ребро
        source-процесс → бокс на каждый DisplayInstance. Рёбра дописываются в
        ``edges`` (мутируется по месту), боксы возвращаются списком.
        """
        boxes_by_display_id: dict[str, DisplayNodeData] = {}
        next_fallback_index = 0

        for disp in topo_dict.get("displays", []):
            if isinstance(disp, dict):
                source_endpoint = disp.get("node_id", "")
                display_id = disp.get("display_id", "")
                binding_name = disp.get("display_name") or ""
            else:
                source_endpoint = getattr(disp, "node_id", "")
                display_id = getattr(disp, "display_id", "")
                binding_name = getattr(disp, "display_name", "") or ""

            if not display_id:
                continue

            # Бокс на display_id (дедуп при fan-in)
            if display_id not in boxes_by_display_id:
                display_name = self.resolve_display_name(display_id) or binding_name
                x, y = view.gui_positions.get(
                    display_id,
                    (600.0, 50.0 + next_fallback_index * 120.0),
                )
                next_fallback_index += 1
                boxes_by_display_id[display_id] = DisplayNodeData(
                    node_id=display_id,
                    display_id=display_id,
                    display_name=display_name,
                    x=x,
                    y=y,
                )

            # Binding-ребро source-плагин-нода → бокс (D.1: node=plugin).
            if source_endpoint:
                source_node = self._endpoint_to_node_id(source_endpoint, topo_dict)
                edges.append(EdgeData(source_id=source_node, target_id=display_id))

        # Task 1.1: дорисовать placed-but-unbound боксы — display_id, которые
        # пользователь разместил через меню, но ещё не привязал проводом. Их нет
        # в topo["displays"], поэтому без этого шага они исчезли бы при reload.
        # Идём ПОСЛЕ построения из topo["displays"] и пропускаем уже существующие
        # display_id (дедуп) — иначе после bind на scene было бы два бокса.
        for display_id in view.placed_display_ids:
            if display_id in boxes_by_display_id:
                continue
            x, y = view.gui_positions.get(display_id, (600.0, 50.0))
            boxes_by_display_id[display_id] = DisplayNodeData(
                node_id=display_id,
                display_id=display_id,
                display_name=self.resolve_display_name(display_id),
                x=x,
                y=y,
            )

        return list(boxes_by_display_id.values())

    def resolve_display_name(self, display_id: str) -> str:
        """Получить человекочитаемое имя канала из DisplayCatalog (best-effort)."""
        try:
            spec = self._displays.resolve(display_id)
            if spec is not None:
                return spec.display_name
        except Exception:
            logger.debug("Не удалось получить имя display '%s'", display_id, exc_info=True)
        return ""
