"""Схема описания операции обработки для каталога."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)
from pydantic import Field, model_validator

from .port_types import PORT_TYPE_IMAGE


@register_schema("PortV3")
class Port(SchemaBase):
    """Описание одного порта операции (вход или выход)."""

    name: Annotated[
        str,
        FieldMeta("Имя порта", info="Уникальное имя порта, e.g. 'in', 'out', 'mask_in'."),
    ]

    data_type: Annotated[
        str,
        FieldMeta(
            "Тип данных",
            info="Тип данных порта: image, mask, detections, contours, any.",
        ),
    ]

    optional: Annotated[
        bool,
        FieldMeta("Опциональный", info="Если True — порт не обязателен для подключения."),
    ] = False


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

    # Входные порты операции: по умолчанию один вход "in" типа "image"
    input_ports: list[Port] = Field(
        default_factory=lambda: [Port(name="in", data_type=PORT_TYPE_IMAGE)]
    )

    # Выходные порты операции: по умолчанию один выход "out" типа "image"
    output_ports: list[Port] = Field(
        default_factory=lambda: [Port(name="out", data_type=PORT_TYPE_IMAGE)]
    )

    # -----------------------------------------------------------------------
    # Phase 9 / Task 9.2 — поля для Pipeline-tab
    # -----------------------------------------------------------------------

    category: Annotated[
        Literal["Input", "ROI", "Preprocess", "Detect", "Measure", "Logic", "Output"] | None,
        FieldMeta(
            "Категория",
            info="Группа в палитре операций: Input/ROI/Preprocess/Detect/Measure/Logic/Output. None — без категории.",
        ),
    ] = None

    multiplicity: Annotated[
        Literal["fixed", "dynamic"],
        FieldMeta(
            "Множественность портов",
            info="fixed — фиксированное число портов; dynamic — переменное (e.g. 1→N region splitter).",
        ),
    ] = "fixed"

    display_capable: Annotated[
        bool,
        FieldMeta(
            "Поддерживает превью",
            info="True — операция умеет публиковать кадр для thumbnail/DisplayWindow.",
        ),
    ] = False

    @model_validator(mode="after")
    def _validate_unique_port_names(self) -> ProcessingOperationDef:
        """Проверяет, что имена портов уникальны внутри input_ports и output_ports."""
        input_names = [p.name for p in self.input_ports]
        if len(input_names) != len(set(input_names)):
            duplicates = {n for n in input_names if input_names.count(n) > 1}
            raise ValueError(f"Дублирующиеся имена входных портов: {duplicates}")

        output_names = [p.name for p in self.output_ports]
        if len(output_names) != len(set(output_names)):
            duplicates = {n for n in output_names if output_names.count(n) > 1}
            raise ValueError(f"Дублирующиеся имена выходных портов: {duplicates}")

        return self


# Публичный алиас для Phase 9 — импортировать как PortDef (используется в Task 9.7)
PortDef = Port  # noqa: E305


__all__ = ["Port", "PortDef", "ProcessingOperationDef"]
