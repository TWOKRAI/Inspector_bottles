"""Vision pipeline hierarchical schema: Pipeline → CameraNode → RegionNode → blocks."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, ClassVar, Dict, Literal, Optional, Union

from pydantic import ConfigDict, Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

from ..camera.schemas import BaseCameraRegisters, HikvisionCameraRegisters, WebcamCameraRegisters
from ..processor.catalog.port_types import PORT_TYPE_IMAGE, are_ports_compatible
from ..processor.catalog.schemas import ProcessingOperationDef
from ..processor.processings.base import BaseProcessingBlock
from .processing_node import ProcessingNode
from .region import Region

CameraRegistersUnion = Union[WebcamCameraRegisters, HikvisionCameraRegisters, BaseCameraRegisters]

CAMERAS_FIELD_ROUTING = FieldRouting(
    channel="control_processor",
    process_targets=("processor",),
)


# ---------------------------------------------------------------------------
# Структурированная ошибка валидации графа (Task 9.3)
# ---------------------------------------------------------------------------


@register_schema("GraphValidationErrorV3")
class GraphValidationError(SchemaBase):
    """Структурированное описание ошибки валидации графа.

    Доменный value object: видим в UI (Inspector panel — Task 9.7),
    сериализуется при логировании в JSON, унифицирован с остальной схемой
    проекта через data_schema_module.

    frozen=True (через model_config) — экземпляры неизменяемы и хешируемы;
    можно класть в set для дедупликации.
    """

    model_config = ConfigDict(
        frozen=True,
        validate_assignment=True,
        populate_by_name=True,
    )

    kind: Annotated[
        Literal[
            "cycle",
            "type_mismatch",
            "unknown_source",
            "unknown_port",
            "unreachable",
            "unknown_operation",
        ],
        FieldMeta(
            "Вид ошибки",
            info="Классификация: cycle, type_mismatch, unknown_source, "
            "unknown_port, unreachable, unknown_operation.",
        ),
    ]

    message: Annotated[
        str,
        FieldMeta("Сообщение", info="Человекочитаемое описание для UI."),
    ]

    camera_id: Annotated[
        Optional[str],
        FieldMeta("Камера", info="ID камеры, в графе которой обнаружена ошибка."),
    ] = None

    region_id: Annotated[
        Optional[str],
        FieldMeta("Регион", info="ID региона."),
    ] = None

    node_id: Annotated[
        Optional[str],
        FieldMeta("Узел", info="ID узла-получателя."),
    ] = None

    source_id: Annotated[
        Optional[str],
        FieldMeta(
            "Источник",
            info="ID источника (для type_mismatch / unknown_source).",
        ),
    ] = None

    port_name: Annotated[
        Optional[str],
        FieldMeta(
            "Порт",
            info="Имя порта (для unknown_port / type_mismatch).",
        ),
    ] = None


# ---------------------------------------------------------------------------
# Приватный хелпер: валидация одного региона
# ---------------------------------------------------------------------------

# Константы 3-color DFS
_WHITE, _GRAY, _BLACK = 0, 1, 2


def _validate_region_graph(
    cam_id: str,
    reg_id: str,
    nodes: Dict[str, ProcessingNode],
    catalog: dict[str, ProcessingOperationDef],
) -> list[GraphValidationError]:
    """Валидация графа одного региона. Возвращает список ошибок (пустой = ок)."""
    errors: list[GraphValidationError] = []

    # Множество нод с неизвестной операцией — для них пропускаем port/type-валидацию
    unknown_ops: set[str] = set()

    # --- Шаг 1: unknown_operation ---
    for nid, node in nodes.items():
        if node.operation_ref not in catalog:
            errors.append(GraphValidationError(
                kind="unknown_operation",
                message=f"Операция '{node.operation_ref}' не найдена в каталоге.",
                camera_id=cam_id,
                region_id=reg_id,
                node_id=nid,
            ))
            unknown_ops.add(nid)

    # --- Шаг 2: unknown_source / unknown_port / type_mismatch ---
    for nid, node in nodes.items():
        if nid in unknown_ops:
            continue
        target_def = catalog[node.operation_ref]
        target_input_ports = {p.name: p for p in target_def.input_ports}

        for inp in node.inputs:
            # "frame" — виртуальный источник, тип image
            if inp.source == "frame":
                # Проверяем input_port у target
                if inp.input_port not in target_input_ports:
                    errors.append(GraphValidationError(
                        kind="unknown_port",
                        message=(
                            f"Нода '{nid}' (операция '{node.operation_ref}') "
                            f"не имеет входного порта '{inp.input_port}'."
                        ),
                        camera_id=cam_id,
                        region_id=reg_id,
                        node_id=nid,
                        port_name=inp.input_port,
                    ))
                else:
                    # type-check: frame всегда image
                    in_type = target_input_ports[inp.input_port].data_type
                    if not are_ports_compatible(PORT_TYPE_IMAGE, in_type):
                        errors.append(GraphValidationError(
                            kind="type_mismatch",
                            message=(
                                f"frame → нода '{nid}' порт '{inp.input_port}': "
                                f"image несовместим с '{in_type}'."
                            ),
                            camera_id=cam_id,
                            region_id=reg_id,
                            node_id=nid,
                            source_id="frame",
                            port_name=inp.input_port,
                        ))
                continue

            # Проверяем существование source-ноды
            if inp.source not in nodes:
                errors.append(GraphValidationError(
                    kind="unknown_source",
                    message=f"Нода '{nid}' ссылается на несуществующий источник '{inp.source}'.",
                    camera_id=cam_id,
                    region_id=reg_id,
                    node_id=nid,
                    source_id=inp.source,
                ))
                continue  # остальные проверки этой связи бессмысленны

            # Source с неизвестной операцией — пропускаем port/type
            if inp.source in unknown_ops:
                continue

            source_def = catalog[nodes[inp.source].operation_ref]
            source_output_ports = {p.name: p for p in source_def.output_ports}

            # output_port у source
            if inp.output_port not in source_output_ports:
                errors.append(GraphValidationError(
                    kind="unknown_port",
                    message=(
                        f"Нода '{nid}' ссылается на выходной порт '{inp.output_port}' "
                        f"ноды '{inp.source}', но такого порта нет."
                    ),
                    camera_id=cam_id,
                    region_id=reg_id,
                    node_id=nid,
                    source_id=inp.source,
                    port_name=inp.output_port,
                ))
                continue  # тип проверять нечего — порт не найден

            # input_port у target
            if inp.input_port not in target_input_ports:
                errors.append(GraphValidationError(
                    kind="unknown_port",
                    message=(
                        f"Нода '{nid}' (операция '{node.operation_ref}') "
                        f"не имеет входного порта '{inp.input_port}'."
                    ),
                    camera_id=cam_id,
                    region_id=reg_id,
                    node_id=nid,
                    port_name=inp.input_port,
                ))
                continue

            # type_mismatch
            out_type = source_output_ports[inp.output_port].data_type
            in_type = target_input_ports[inp.input_port].data_type
            if not are_ports_compatible(out_type, in_type):
                errors.append(GraphValidationError(
                    kind="type_mismatch",
                    message=(
                        f"Несовместимые типы: нода '{inp.source}' порт '{inp.output_port}' "
                        f"({out_type}) → нода '{nid}' порт '{inp.input_port}' ({in_type})."
                    ),
                    camera_id=cam_id,
                    region_id=reg_id,
                    node_id=nid,
                    source_id=inp.source,
                    port_name=inp.input_port,
                ))

    # --- Шаг 3: cycle detection (3-color DFS) ---
    # Строим adjacency: source → [targets] (по inputs)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for nid, node in nodes.items():
        for inp in node.inputs:
            if inp.source != "frame" and inp.source in nodes:
                adjacency[inp.source].append(nid)

    color: dict[str, int] = {nid: _WHITE for nid in nodes}
    cycle_nodes: set[str] = set()

    def _dfs_cycle(nid: str) -> bool:
        """DFS для обнаружения циклов. Возвращает True если найден цикл."""
        color[nid] = _GRAY
        for neighbor in adjacency.get(nid, []):
            if color[neighbor] == _GRAY:
                # back-edge → цикл
                cycle_nodes.add(nid)
                cycle_nodes.add(neighbor)
                return True
            if color[neighbor] == _WHITE:
                if _dfs_cycle(neighbor):
                    if color[nid] == _GRAY:
                        cycle_nodes.add(nid)
                    return True
        color[nid] = _BLACK
        return False

    for nid in nodes:
        if color[nid] == _WHITE:
            _dfs_cycle(nid)

    if cycle_nodes:
        errors.append(GraphValidationError(
            kind="cycle",
            message=f"Обнаружен цикл в графе. Участники: {sorted(cycle_nodes)}.",
            camera_id=cam_id,
            region_id=reg_id,
        ))

    # --- Шаг 4: unreachable (достижимость от frame) ---
    # Стартовый набор — ноды с хотя бы одним input.source == "frame"
    frame_starts = {nid for nid, node in nodes.items() if any(inp.source == "frame" for inp in node.inputs)}

    if frame_starts:
        # BFS/DFS вперёд по adjacency (source → targets)
        visited: set[str] = set()
        stack = list(frame_starts)
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for neighbor in adjacency.get(current, []):
                if neighbor not in visited:
                    stack.append(neighbor)

        unreachable = set(nodes.keys()) - visited
        for nid in sorted(unreachable):
            errors.append(GraphValidationError(
                kind="unreachable",
                message=f"Нода '{nid}' недостижима из frame-источника.",
                camera_id=cam_id,
                region_id=reg_id,
                node_id=nid,
            ))

    return errors


# ---------------------------------------------------------------------------
# Схемы Pipeline
# ---------------------------------------------------------------------------


@register_schema("RegionNodeV3")
class RegionNode(Region):
    """Region in pipeline: ROI fields + dict of processing blocks (legacy) + nodes (Phase 5a)."""

    # Устаревшее поле — оставлено для обратной совместимости
    processing_blocks: Dict[str, BaseProcessingBlock] = Field(default_factory=dict)

    # Новый граф узлов обработки (Phase 5a — линейная цепочка, Phase 8 — полный граф)
    nodes: Dict[str, ProcessingNode] = Field(default_factory=dict)


@register_schema("CameraNodeV3")
class CameraNode(SchemaBase):
    """Camera in pipeline: registers and regions."""

    enabled: bool = True
    registers: CameraRegistersUnion = Field(default_factory=BaseCameraRegisters)
    regions: Dict[str, RegionNode] = Field(default_factory=dict)


@register_schema("PipelineV3")
class Pipeline(SchemaBase):
    """Root pipeline schema: dict of cameras."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

    cameras: Annotated[
        Dict[str, CameraNode],
        FieldMeta("Cameras", info="Cameras → regions → processing blocks.", routing=CAMERAS_FIELD_ROUTING),
    ] = Field(default_factory=dict)

    def validate_graph(
        self,
        catalog: dict[str, ProcessingOperationDef],
    ) -> list[GraphValidationError]:
        """Полная валидация всех графов в pipeline. Не бросает — собирает ошибки.

        Покрывает каждый region.nodes:
          1. unknown_operation: operation_ref не в catalog
          2. unknown_source: NodeInput.source не "frame" и не в region.nodes
          3. unknown_port: порт не найден в определении операции
          4. type_mismatch: are_ports_compatible(out_type, in_type) is False
          5. cycle: цикл в графе региона
          6. unreachable: нода не достижима из frame-источника

        Returns:
            Список ошибок (пустой = всё ок).
        """
        errors: list[GraphValidationError] = []
        for cam_id, cam in self.cameras.items():
            for reg_id, reg in cam.regions.items():
                errors.extend(_validate_region_graph(cam_id, reg_id, reg.nodes, catalog))
        return errors


__all__ = ["CameraRegistersUnion", "RegionNode", "CameraNode", "Pipeline", "GraphValidationError"]
