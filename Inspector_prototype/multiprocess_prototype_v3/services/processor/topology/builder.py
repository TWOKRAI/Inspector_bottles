"""RouterTopology — схемы и трансформация Pipeline → RouterTopology.

Часть A (Task 9.5): доменные схемы через data_schema_module.
Часть B (Task 9.5): чистая функция to_router_topology().
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Annotated

from pydantic import ConfigDict

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)

from multiprocess_prototype_v3.registers.pipeline.schemas import Pipeline
from multiprocess_prototype_v3.registers.processor.catalog.schemas import ProcessingOperationDef

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Доменные схемы (SchemaBase — пересекают границы модулей, видны UI)
# ---------------------------------------------------------------------------


@register_schema("ChannelSpecV3")
class ChannelSpec(SchemaBase):
    """Описание одного канала Router.

    Именование: '{channel_prefix or node_id}.{port_name}'.
    Создаётся для каждого output-порта каждой включённой ноды.
    """

    model_config = ConfigDict(frozen=True)

    channel_name: Annotated[
        str,
        FieldMeta(
            "Имя канала",
            info="Формат: '{node_id}.{port_name}' или '{channel_prefix}.{port_name}'.",
        ),
    ]

    process_id: Annotated[
        str,
        FieldMeta(
            "Процесс-владелец",
            info="ID процесса, в котором выполняется нода-источник.",
        ),
    ]

    payload_kind: Annotated[
        str,
        FieldMeta(
            "Тип данных",
            info="'image' | 'mask' | 'detections' | ... — для будущей SHM-маршрутизации (Task 9.6).",
        ),
    ]


@register_schema("EdgeSpecV3")
class EdgeSpec(SchemaBase):
    """Описание одного ребра DAG.

    Связывает source_channel (output-порт source-ноды) с target_node_id + target_input_port.
    """

    model_config = ConfigDict(frozen=True)

    source_channel: Annotated[
        str,
        FieldMeta(
            "Канал-источник",
            info="channel_name ноды-источника + port ('{prefix}.{port}').",
        ),
    ]

    target_node_id: Annotated[
        str,
        FieldMeta(
            "Целевая нода",
            info="node_id целевой ноды.",
        ),
    ]

    target_input_port: Annotated[
        str,
        FieldMeta(
            "Целевой порт",
            info="Имя входного порта target-ноды.",
        ),
    ]

    cross_process: Annotated[
        bool,
        FieldMeta(
            "Кросс-процесс",
            info="True если source.process_id != target.process_id (для Task 9.6 SHM).",
        ),
    ]


@register_schema("RouterTopologyV3")
class RouterTopology(SchemaBase):
    """Полное описание router-топологии для одного Pipeline.

    Транслируется в register_channel / register_route / register_broadcast_route
    вызовы через apply_topology(router, topology).

    Сериализуется для отображения в Pipeline-tab (Task 9.7+).
    """

    channels: Annotated[
        list[ChannelSpec],
        FieldMeta(
            "Каналы",
            info="Список всех каналов топологии (по одному на output-порт ноды).",
        ),
    ] = []

    edges: Annotated[
        list[EdgeSpec],
        FieldMeta(
            "Рёбра",
            info="Список всех рёбер DAG.",
        ),
    ] = []

    broadcast_routes: Annotated[
        dict[str, list[str]],
        FieldMeta(
            "Broadcast-маршруты",
            info="source_channel → [target_channel_1, ...] для fan-out. "
            "Один таргет = обычная связь, два+ = broadcast.",
        ),
    ] = {}

    process_ids: Annotated[
        list[str],
        FieldMeta(
            "Процессы",
            info="Уникальные process_id, задействованные в Pipeline.",
        ),
    ] = []

    process_groups: Annotated[
        dict[str, list[str]],
        FieldMeta(
            "Группы процессов",
            info="process_id → list[node_id]. Какие ноды выполняются в каком процессе.",
        ),
    ] = {}

    process_channels: Annotated[
        dict[str, list[str]],
        FieldMeta(
            "Каналы процессов",
            info="process_id → list[channel_name]. Какие каналы принадлежат какому процессу. "
            "Используется при настройке SHM middleware для cross-process рёбер.",
        ),
    ] = {}


# ---------------------------------------------------------------------------
# Часть B: чистая функция to_router_topology()
# ---------------------------------------------------------------------------


def _channel_name_for_node(node_id: str, channel_prefix: str | None, port_name: str) -> str:
    """Формирует имя канала: '{channel_prefix or node_id}.{port_name}'."""
    prefix = channel_prefix if channel_prefix else node_id
    return f"{prefix}.{port_name}"


def to_router_topology(
    pipeline: Pipeline,
    catalog: dict[str, ProcessingOperationDef],
) -> RouterTopology:
    """Трансформировать Pipeline → RouterTopology (чистая функция, без сайд-эффектов).

    Имя канала: {channel_prefix or node_id}.{port_name}.
    payload_kind = port.data_type из output_ports операции в каталоге.
    cross_process = source.process_id != target.process_id.

    Несколько edge'ов с одинаковым source_channel → broadcast_routes (fan-out).

    Важно: функция НЕ проверяет валидность графа.
    Перед вызовом используйте pipeline.validate_graph(catalog).
    """
    channels: list[ChannelSpec] = []
    edges: list[EdgeSpec] = []
    process_ids_set: set[str] = set()

    # node_id → ProcessingNode (для поиска process_id по source)
    all_nodes: dict[str, object] = {}

    # process_id → list[node_id] — группировка нод по процессам
    groups: dict[str, list[str]] = defaultdict(list)
    # process_id → list[channel_name] — каналы каждого процесса
    proc_channels: dict[str, list[str]] = defaultdict(list)

    for _cam_id, cam in pipeline.cameras.items():
        for _reg_id, reg in cam.regions.items():
            for node_id, node in reg.nodes.items():
                # Disabled ноды исключаем из топологии
                if not node.enabled:
                    continue

                all_nodes[node_id] = node
                process_ids_set.add(node.process_id)
                groups[node.process_id].append(node_id)

                # --- Каналы для output-портов ---
                op_def = catalog.get(node.operation_ref)

                if op_def is not None and op_def.output_ports:
                    # Стандартный путь: фиксированные порты из каталога
                    for port in op_def.output_ports:
                        ch_name = _channel_name_for_node(
                            node_id, node.channel_prefix, port.name,
                        )
                        channels.append(ChannelSpec(
                            channel_name=ch_name,
                            process_id=node.process_id,
                            payload_kind=port.data_type,
                        ))
                        proc_channels[node.process_id].append(ch_name)
                elif node.outputs:
                    # Динамический путь (multiplicity=dynamic, e.g. region_splitter):
                    # output_ports из каталога пустые, используем node.outputs
                    for node_output in node.outputs:
                        ch_name = _channel_name_for_node(
                            node_id, node.channel_prefix, node_output.port_name,
                        )
                        # payload_kind неизвестен из каталога — ставим 'any'
                        channels.append(ChannelSpec(
                            channel_name=ch_name,
                            process_id=node.process_id,
                            payload_kind="any",
                        ))
                        proc_channels[node.process_id].append(ch_name)

                # --- Рёбра для inputs ---
                for inp in node.inputs:
                    if inp.source == "frame":
                        # Виртуальный источник кадра от камеры.
                        # Создаём source_channel с фиксированным именем 'frame.out'.
                        source_ch = "frame.out"
                        # frame — виртуальный, cross-process не определяем
                        edges.append(EdgeSpec(
                            source_channel=source_ch,
                            target_node_id=node_id,
                            target_input_port=inp.input_port,
                            cross_process=False,
                        ))
                        continue

                    # Source — реальная нода
                    source_node = all_nodes.get(inp.source)
                    if source_node is None:
                        # Source не найден (может быть disabled или из другого региона).
                        # Не проверяем валидность — это задача validate_graph.
                        logger.debug(
                            "to_router_topology: source '%s' не найден для ноды '%s'",
                            inp.source,
                            node_id,
                        )
                        continue

                    source_ch = _channel_name_for_node(
                        inp.source,
                        getattr(source_node, "channel_prefix", None),
                        inp.output_port,
                    )

                    is_cross = getattr(source_node, "process_id", "processor") != node.process_id

                    edges.append(EdgeSpec(
                        source_channel=source_ch,
                        target_node_id=node_id,
                        target_input_port=inp.input_port,
                        cross_process=is_cross,
                    ))

    # --- Группировка broadcast_routes ---
    # Собираем: source_channel → список target_channel_name (для target-нод)
    source_to_targets: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        # target_channel = имя канала, в который надо доставить данные.
        # Для регистрации route в router'е нам нужно знать channel_name target-ноды.
        # Однако route привязывается к input-порту ноды, а не к output-каналу.
        # В контексте router: route(key=source_channel) → channel_name (target-input).
        # Target-канал = '{target_node_id or target_prefix}.{target_input_port}'
        target_node = all_nodes.get(edge.target_node_id)
        target_prefix = getattr(target_node, "channel_prefix", None) if target_node else None
        target_ch = _channel_name_for_node(
            edge.target_node_id, target_prefix, edge.target_input_port,
        )
        source_to_targets[edge.source_channel].append(target_ch)

    broadcast_routes: dict[str, list[str]] = {}
    for src_ch, targets in source_to_targets.items():
        if len(targets) > 1:
            broadcast_routes[src_ch] = targets

    return RouterTopology(
        channels=channels,
        edges=edges,
        broadcast_routes=broadcast_routes,
        process_ids=sorted(process_ids_set),
        process_groups=dict(groups),
        process_channels=dict(proc_channels),
    )


__all__ = [
    "ChannelSpec",
    "EdgeSpec",
    "RouterTopology",
    "to_router_topology",
]
