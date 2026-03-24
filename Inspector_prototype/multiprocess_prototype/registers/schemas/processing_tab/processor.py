# -*- coding: utf-8 -*-
"""
ProcessorRegisters — параметры цветовой детекции и площади контура (Inspector prototype).

Маршрутизация: processor.
"""
from typing import Annotated, ClassVar, List

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

PROCESSOR_ROUTING = FieldRouting(channel="control_processor")


class ProcessorRegisters(SchemaBase):
    """Регистры параметров цветовой детекции (BGR) и площади пятна."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("processor",),
    )

    color_lower: Annotated[
        List[int],
        FieldMeta(
            "BGR Lower",
            info="Нижняя граница BGR для маски (B, G, R).",
            routing=PROCESSOR_ROUTING,
        ),
    ] = [0, 0, 150]

    color_upper: Annotated[
        List[int],
        FieldMeta(
            "BGR Upper",
            info="Верхняя граница BGR для маски (B, G, R).",
            routing=PROCESSOR_ROUTING,
        ),
    ] = [100, 100, 255]

    min_area: Annotated[
        int,
        FieldMeta(
            "Мин. площадь",
            info="Минимальная площадь контура (px).",
            min=10,
            max=5000,
            unit="px",
            routing=PROCESSOR_ROUTING,
        ),
    ] = 500

    max_area: Annotated[
        int,
        FieldMeta(
            "Макс. площадь",
            info="Максимальная площадь контура (px). 0 — без ограничения.",
            min=0,
            max=50000,
            unit="px",
            routing=PROCESSOR_ROUTING,
        ),
    ] = 50000
