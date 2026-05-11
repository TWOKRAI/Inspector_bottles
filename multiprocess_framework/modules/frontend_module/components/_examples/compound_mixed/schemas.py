# -*- coding: utf-8 -*-
"""
Два поля одного логического регистра: bool + float для ``CompoundControl`` (чекбокс + слайдер).
"""
from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from multiprocess_framework.modules.frontend_module.schema_adapter import (

    FieldMeta,

    FieldRouting,

    RegisterDispatchMeta,

    SchemaBase,

    register_schema,

)

EXAMPLE_MIXED_ROUTING = FieldRouting(channel="control_example")


@register_schema("ExampleMixedBoolRegister")
class ExampleMixedBoolRegister(SchemaBase):
    """Булево поле; тот же ``BINDING_REGISTER``, что у числового поля ниже."""

    BINDING_REGISTER: ClassVar[str] = "example_data_schema_mixed"
    BINDING_FIELD: ClassVar[str] = "mix_enabled"

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    mix_enabled: Annotated[
        bool,
        FieldMeta("Включено", info="Чекбокс в составном ряду.", routing=EXAMPLE_MIXED_ROUTING),
    ] = False


@register_schema("ExampleMixedFloatRegister")
class ExampleMixedFloatRegister(SchemaBase):
    """Числовое поле того же регистра ``example_data_schema_mixed``."""

    BINDING_REGISTER: ClassVar[str] = "example_data_schema_mixed"
    BINDING_FIELD: ClassVar[str] = "mix_level"

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    mix_level: Annotated[
        float,
        FieldMeta(
            "Уровень",
            info="Слайдер в составном ряду.",
            routing=EXAMPLE_MIXED_ROUTING,
            min=0.0,
            max=100.0,
            transfer_k=0.1,
            round_k=1,
        ),
    ] = 50.0


@register_schema("ExampleCompoundMixedUiConfig")
class ExampleCompoundMixedUiConfig(SchemaBase):
    """UI чекбокса, слайдера и раскладки контейнера."""

    mix_checkbox_label: Annotated[str, FieldMeta("Подпись чекбокса")] = ""
    mix_checkbox_tooltip: Annotated[str, FieldMeta("Подсказка чекбокса")] = ""
    mix_checkbox_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки чекбокса"),
    ] = "left"
    mix_checkbox_widget_enabled: Annotated[
        bool,
        FieldMeta("Чекбокс доступен"),
    ] = True

    mix_slider_label: Annotated[str, FieldMeta("Подпись слайдера")] = ""
    mix_slider_tooltip: Annotated[str, FieldMeta("Подсказка слайдера")] = ""
    mix_slider_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки слайдера"),
    ] = "left"
    mix_slider_show_ticks: Annotated[bool, FieldMeta("Деления слайдера")] = False
    mix_slider_widget_enabled: Annotated[bool, FieldMeta("Слайдер доступен")] = True

    compound_orientation: Annotated[
        Literal["horizontal", "vertical"],
        FieldMeta("Ориентация контейнера"),
    ] = "horizontal"
    compound_spacing: Annotated[int, FieldMeta("Отступ между контролами")] = 10
