"""Модель узла обработки внутри региона (Processing Chain, Phase 5a)."""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, Tuple
from uuid import uuid4

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("NodeInputV3")
class NodeInput(SchemaBase):
    """Описывает входное соединение узла: откуда брать данные."""

    source: Annotated[
        str,
        FieldMeta("Источник", info="node_id предыдущего узла или 'frame' для входного кадра."),
    ]

    output_port: Annotated[
        str,
        FieldMeta("Выходной порт", info="Имя выходного порта источника. Phase 8 — пока default 'out'."),
    ] = "out"

    input_port: Annotated[
        str,
        FieldMeta(
            "Входной порт",
            info="В какой входной порт target-ноды подключается соединение. "
            "Для линейных цепочек всегда 'in', для DAG — произвольный порт.",
        ),
    ] = "in"


@register_schema("ProcessingNodeV3")
class ProcessingNode(SchemaBase):
    """Узел обработки внутри региона. Часть графа обработки (Phase 5a — линейная цепочка)."""

    node_id: Annotated[
        str,
        FieldMeta("ID узла", info="UUID узла как строка. Генерируется автоматически."),
    ] = Field(default_factory=lambda: str(uuid4()))

    operation_ref: Annotated[
        str,
        FieldMeta("Операция", info="Ключ операции в каталоге (type_key из ProcessingOperationDef)."),
    ]

    params: Annotated[
        Dict[str, Any],
        FieldMeta("Параметры", info="Параметры операции — произвольный словарь, специфичный для операции."),
    ] = Field(default_factory=dict)

    enabled: Annotated[
        bool,
        FieldMeta("Включён", info="Если False — узел пропускается при выполнении цепочки."),
    ] = True

    process_id: Annotated[
        str,
        FieldMeta("Процесс", info="В каком процессе выполнять узел (по умолчанию 'processor')."),
    ] = "processor"

    worker_id: Annotated[
        Optional[str],
        FieldMeta("Worker", info="Thread worker внутри процесса. None — выбирается автоматически."),
    ] = None

    inputs: Annotated[
        List[NodeInput],
        FieldMeta(
            "Входы",
            info="Входные соединения узла. В Phase 5a заполняются автоматически линейно, поле скрыто в UI.",
        ),
    ] = Field(default_factory=list)

    position: Annotated[
        Optional[Tuple[float, float]],
        FieldMeta("Позиция", info="Координаты узла на графе (Phase 8). Пока не используется."),
    ] = None


__all__ = ["NodeInput", "ProcessingNode"]
