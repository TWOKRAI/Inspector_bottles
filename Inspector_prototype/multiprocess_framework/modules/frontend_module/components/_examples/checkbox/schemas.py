# -*- coding: utf-8 -*-
"""
Две `SchemaBase`: **регистр** (`ExampleCheckboxValueRegister`) и **UI** (`ExampleCheckboxUiConfig`).

Имя регистра и поля для `BindingConfig` задаются `ClassVar` на классе регистра (`BINDING_*`).
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

EXAMPLE_CHECKBOX_ROUTING = FieldRouting(channel="control_example")


@register_schema("ExampleCheckboxValueRegister")
class ExampleCheckboxValueRegister(SchemaBase):
    """
    Булево поле регистра + `FieldMeta` для `ResolvedMeta` и маршрутизации.

    ``BINDING_FIELD`` должен совпадать с именем поля-схемы ниже (`feature_enabled`).
    """

    BINDING_REGISTER: ClassVar[str] = "example_data_schema_checkbox"
    BINDING_FIELD: ClassVar[str] = "feature_enabled"

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("example",),
    )

    feature_enabled: Annotated[
        bool,
        FieldMeta(
            "Демо-фича",
            info="Значение в регистре; подпись UI, если не задана в `ExampleCheckboxUiConfig`.",
            routing=EXAMPLE_CHECKBOX_ROUTING,
        ),
    ] = False


@register_schema("ExampleCheckboxUiConfig")
class ExampleCheckboxUiConfig(SchemaBase):
    """Только отображение; не участвует в `register_update`. Пустой `checkbox_label` → метаданные регистра."""

    checkbox_label: Annotated[
        str,
        FieldMeta(
            "Подпись",
            info="Пустая строка: адаптер не переопределяет label (берётся из FieldMeta регистра).",
        ),
    ] = ""

    checkbox_tooltip: Annotated[
        str,
        FieldMeta("Подсказка", info="Tooltip метки; пусто — описание из регистра."),
    ] = ""

    checkbox_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"

    checkbox_widget_enabled: Annotated[
        bool,
        FieldMeta(
            "Виджет доступен",
            info="Не путать с `feature_enabled` в регистре.",
        ),
    ] = True
