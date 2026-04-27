"""Схема конфигурации display-окна."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("DisplayWindowConfigV3")
class DisplayWindowConfig(SchemaBase):
    """Конфигурация виджета display-окна."""

    # Уникальный идентификатор окна (win_0, win_1, ...)
    window_id: Annotated[
        str,
        FieldMeta("ID окна", info="Уникальный идентификатор окна отображения."),
    ]

    # Начальный источник кадров (camera_N или processor ref)
    initial_source: Annotated[
        str,
        FieldMeta(
            "Начальный источник",
            info="source_ref при открытии окна. Пустая строка — без источника.",
        ),
    ] = ""

    # Заголовок окна
    title: Annotated[
        str,
        FieldMeta("Заголовок", info="Текст заголовка display-окна."),
    ] = "Display"


__all__ = ["DisplayWindowConfig"]
