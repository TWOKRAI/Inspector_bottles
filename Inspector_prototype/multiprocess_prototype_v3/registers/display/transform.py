"""Схема трансформации кадра для display-подписки."""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("DisplayTransformV3")
class DisplayTransform(SchemaBase):
    """Параметры трансформации кадра перед отображением в окне."""

    # Целевая ширина после resize (None = не масштабировать)
    resize_width: Annotated[
        int | None,
        FieldMeta("Ширина resize", info="Целевая ширина кадра (px). None — без масштабирования."),
    ] = None

    # Целевая высота после resize (None = не масштабировать)
    resize_height: Annotated[
        int | None,
        FieldMeta("Высота resize", info="Целевая высота кадра (px). None — без масштабирования."),
    ] = None

    # Включить/выключить наложение overlay (статистика, bbox и т.п.)
    overlay_enabled: Annotated[
        bool,
        FieldMeta("Overlay", info="Включить наложение графики поверх кадра."),
    ] = True

    # Лимит FPS отображения (не влияет на источник)
    fps_limit: Annotated[
        int,
        FieldMeta("Лимит FPS", info="Максимальная частота обновления окна (1..120).", min=1, max=120, unit="fps"),
    ] = 30


__all__ = ["DisplayTransform"]
