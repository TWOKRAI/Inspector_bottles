# -*- coding: utf-8 -*-
"""
Две `SchemaBase`: **регистр** (`ExampleComboValueRegister`) и **UI** (`ExampleComboUiConfig`).

Имя регистра и поля для `BindingConfig` задаются `ClassVar` на классе регистра (`BINDING_*`).
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

EXAMPLE_COMBO_ROUTING = FieldRouting(channel="control_example")


@register_schema("ExampleComboValueRegister")
class ExampleComboValueRegister(SchemaBase):
    """
    Literal-поле + `FieldMeta` для `ResolvedMeta` и маршрутизации.

    ``BINDING_FIELD`` должен совпадать с именем поля-схемы ниже (`mode`).
    """

    BINDING_REGISTER: ClassVar[str] = "example_data_schema_combo"
    BINDING_FIELD: ClassVar[str] = "mode"

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    mode: Annotated[
        Literal["auto", "manual", "off"],
        FieldMeta(
            "Режим работы",
            info="Литерал-варианты приходят в combo как items; UI-подпись из FieldMeta, если в UI не задана.",
            routing=EXAMPLE_COMBO_ROUTING,
        ),
    ] = "auto"


@register_schema("ExampleComboUiConfig")
class ExampleComboUiConfig(SchemaBase):
    """Только отображение; не участвует в `register_update`."""

    combo_label: Annotated[
        str,
        FieldMeta(
            "Подпись",
            info="Пустая строка: адаптер не переопределяет label (берётся из FieldMeta регистра).",
        ),
    ] = ""

    combo_tooltip: Annotated[
        str,
        FieldMeta("Подсказка", info="Tooltip метки; пусто — описание из регистра."),
    ] = ""

    combo_placeholder: Annotated[
        str,
        FieldMeta("Placeholder", info="Текст пустого выбора (первый пустой item)."),
    ] = ""

    combo_widget_enabled: Annotated[
        bool,
        FieldMeta(
            "Виджет доступен",
            info="Не путать с тем, что приходит из регистра.",
        ),
    ] = True
