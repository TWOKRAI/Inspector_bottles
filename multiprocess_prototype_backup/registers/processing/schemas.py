"""ProcessingConfig — конфигурация обработки по регионам (Layer 2).

Описывает ЧТО ДЕЛАТЬ с данными из каждого региона:
- Какие processing nodes (blur, detect, threshold...)
- Какие параметры у каждого node
- В каком порядке выполнять

Ключи регионов (camera_0_main, camera_0_roi1) — общие с SourceTopology (Layer 1).
Потребитель: ProcessorProcess (обработка кадров).
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Dict

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

from ..pipeline.processing_node import ProcessingNode

# Routing: processing → processor
PROCESSING_ROUTING = FieldRouting(
    channel="control_processing",
    process_targets=("processor",),
)


@register_schema("RegionPipelineConfigV3")
class RegionPipelineConfig(SchemaBase):
    """Pipeline обработки для одного региона."""

    enabled: Annotated[
        bool,
        FieldMeta("Включён", info="Включить/выключить обработку региона."),
    ] = True

    nodes: Annotated[
        Dict[str, ProcessingNode],
        FieldMeta("Узлы", info="Граф обработки: node_id → ProcessingNode."),
    ] = Field(default_factory=dict)


@register_schema("ProcessingConfigV3")
class ProcessingConfig(SchemaBase):
    """Конфигурация обработки — Layer 2.

    Ключи region_pipelines совпадают с ключами regions в SourceTopology.
    """

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

    region_pipelines: Annotated[
        Dict[str, RegionPipelineConfig],
        FieldMeta(
            "Pipelines регионов",
            info="Processing chain per region. Ключи = ключи регионов из SourceTopology.",
        ),
    ] = Field(default_factory=dict)


__all__ = [
    "RegionPipelineConfig",
    "ProcessingConfig",
    "PROCESSING_ROUTING",
]
