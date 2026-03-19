# -*- coding: utf-8 -*-
"""
RendererRegisters — параметры отображения (Original, Mask, Contours).

Общие для backend (Renderer) и frontend.
Маршрутизация: renderer.
"""
from typing import Annotated

from data_schema_module import FieldMeta, FieldRouting, SchemaBase

RENDERER_ROUTING = FieldRouting(channel="control_renderer")


class RendererRegisters(SchemaBase):
    """Регистры параметров отображения рендерера."""

    show_original: Annotated[
        bool,
        FieldMeta(
            "Original",
            info="Показывать оригинальный кадр.",
            routing=RENDERER_ROUTING,
        ),
    ] = True

    show_mask: Annotated[
        bool,
        FieldMeta(
            "Mask",
            info="Показывать маску.",
            routing=RENDERER_ROUTING,
        ),
    ] = True

    draw_contours: Annotated[
        bool,
        FieldMeta(
            "Contours",
            info="Рисовать контуры на изображении.",
            routing=RENDERER_ROUTING,
        ),
    ] = True
