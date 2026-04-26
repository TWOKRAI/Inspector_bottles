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


@register_schema("NodeOutputV3")
class NodeOutput(SchemaBase):
    """Описывает выходное соединение узла: куда направлять данные."""

    port_name: Annotated[
        str,
        FieldMeta("Порт", info="Имя выходного порта операции (e.g. 'out', 'mask')."),
    ]

    display_target: Annotated[
        Optional[str],
        FieldMeta(
            "Display target",
            info="id окна DisplayWindow для публикации. None = не публиковать.",
        ),
    ] = None


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

    # --- Phase 9 / Task 9.3 — выходной роутинг и display ---

    outputs: Annotated[
        List[NodeOutput],
        FieldMeta(
            "Выходы",
            info="Пер-портовые настройки роутинга выходов. "
            "Пустой список = дефолтное поведение (broadcast в каналы по имени).",
        ),
    ] = Field(default_factory=list)

    display_targets: Annotated[
        List[str],
        FieldMeta(
            "Display targets",
            info="Список display-window id, куда публикуется главный (display_capable) выход ноды. "
            "Используется в Task 9.8 (thumbnail) и в DisplayRouter.",
        ),
    ] = Field(default_factory=list)

    channel_prefix: Annotated[
        Optional[str],
        FieldMeta(
            "Префикс канала",
            info="Опциональный префикс канала. None → используется node_id. "
            "Иначе — {channel_prefix}.{port_name}. "
            "Полезно когда нужны человекочитаемые имена каналов.",
        ),
    ] = None


__all__ = ["NodeInput", "NodeOutput", "ProcessingNode"]
