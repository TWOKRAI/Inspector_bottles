# -*- coding: utf-8 -*-
"""
Регистр + UI-схема для демо-спинбокса (аналог ``slider/schemas.py``).
"""
from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

EXAMPLE_SPINBOX_ROUTING = FieldRouting(channel="control_example")


@register_schema("ExampleSpinboxValueRegister")
class ExampleSpinboxValueRegister(SchemaBase):
    """Числовое поле + ``FieldMeta`` для ``ResolvedMeta`` (спинбокс)."""

    BINDING_REGISTER: ClassVar[str] = "example_data_schema_spinbox"
    BINDING_FIELD: ClassVar[str] = "demo_spinbox_value"

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    demo_spinbox_value: Annotated[
        float,
        FieldMeta(
            "Демо-значение",
            info="Число в регистре; подпись из UI-схемы или FieldMeta.",
            routing=EXAMPLE_SPINBOX_ROUTING,
            min=0.0,
            max=100.0,
            transfer_k=0.1,
            round_k=1,
        ),
    ] = 25.0


@register_schema("ExampleSpinboxUiConfig")
class ExampleSpinboxUiConfig(SchemaBase):
    """Только отображение; не участвует в ``register_update``."""

    spinbox_label: Annotated[
        str,
        FieldMeta(
            "Подпись",
            info="Пустая строка: label из метаданных регистра.",
        ),
    ] = ""

    spinbox_tooltip: Annotated[
        str,
        FieldMeta("Подсказка", info="Пусто — описание из регистра."),
    ] = ""

    spinbox_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"

    spinbox_min: Annotated[
        float | None,
        FieldMeta("Мин.", info="None — из метаданных регистра."),
    ] = None

    spinbox_max: Annotated[
        float | None,
        FieldMeta("Макс.", info="None — из метаданных регистра."),
    ] = None

    spinbox_widget_enabled: Annotated[
        bool,
        FieldMeta("Виджет доступен"),
    ] = True
