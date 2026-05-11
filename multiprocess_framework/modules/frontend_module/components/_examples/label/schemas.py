# -*- coding: utf-8 -*-
"""
Только UI-схема для ``LabelView`` (без привязки к регистру).
"""
from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.frontend_module.schema_adapter import FieldMeta, SchemaBase, register_schema


@register_schema("ExampleLabelUiConfig")
class ExampleLabelUiConfig(SchemaBase):
    """Текст подписи и отображение; значение регистра не используется."""

    label_text: Annotated[
        str,
        FieldMeta("Текст", info="Пусто — на виджете показывается «—»."),
    ] = ""

    tooltip_text: Annotated[str, FieldMeta("Подсказка")] = ""

    label_position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция (для LabelConfig)"),
    ] = "left"

    label_visible: Annotated[bool, FieldMeta("Видимость")] = True
