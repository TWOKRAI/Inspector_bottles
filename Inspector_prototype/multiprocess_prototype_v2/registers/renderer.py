# -*- coding: utf-8 -*-
"""
RendererRegisters — параметры отображения (Inspector prototype).

Маршрутизация: renderer.
"""
from typing import Annotated, ClassVar

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

RENDERER_ROUTING = FieldRouting(channel="control_renderer")


@register_schema("RendererRegistersV3")
class RendererRegisters(SchemaBase):
    """Регистры параметров отображения рендерера."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("renderer",),
    )

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

    draw_bboxes: Annotated[
        bool,
        FieldMeta(
            "BBox",
            info="Рисовать bbox вокруг детекций.",
            routing=RENDERER_ROUTING,
        ),
    ] = True

    save_frames: Annotated[
        bool,
        FieldMeta(
            "Save frames",
            info="Сохранять кадры в output_dir.",
            routing=RENDERER_ROUTING,
        ),
    ] = False
