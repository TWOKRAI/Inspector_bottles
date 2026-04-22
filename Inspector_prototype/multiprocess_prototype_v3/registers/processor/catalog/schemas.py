"""Схема описания операции обработки для каталога."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("ProcessingOperationDefV3")
class ProcessingOperationDef(SchemaBase):
    """Описание одной операции обработки в каталоге."""

    name: Annotated[
        str,
        FieldMeta("Имя операции", info="Человекочитаемое название операции."),
    ]

    type_key: Annotated[
        str,
        FieldMeta("Ключ типа", info="Уникальный строковый ключ операции, e.g. 'color_detection'."),
    ]

    params_schema: Annotated[
        str,
        FieldMeta(
            "Схема параметров",
            info="Dotted path к классу параметров, e.g. 'registers.processor.processings.color_detection.ColorDetectionParams'.",
        ),
    ]

    module_path: Annotated[
        str,
        FieldMeta(
            "Путь к модулю",
            info="Dotted path к классу операции, e.g. 'services.processor.operations.color_detection_op.ColorDetectionOp'.",
        ),
    ]

    on_error: Annotated[
        Literal["skip", "fail_region", "fail_camera"],
        FieldMeta(
            "Поведение при ошибке",
            info="skip — пропустить; fail_region — провалить регион; fail_camera — провалить камеру.",
        ),
    ] = "skip"

    description: Annotated[
        str,
        FieldMeta("Описание", info="Краткое описание назначения операции."),
    ] = ""


__all__ = ["ProcessingOperationDef"]
