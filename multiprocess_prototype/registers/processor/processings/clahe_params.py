"""Параметры операции выравнивания гистограммы CLAHE."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("ClaheParamsV3")
class ClaheParams(ProcessingParamsBase):
    """Параметры операции CLAHE (Contrast Limited Adaptive Histogram Equalization)."""

    type: Literal["clahe"] = "clahe"

    clip_limit: Annotated[
        float,
        FieldMeta("Предел клиппинга", info="Ограничение контраста для CLAHE.", min=0.1, max=40.0),
    ] = 2.0

    tile_grid_size: Annotated[
        int,
        FieldMeta("Размер сетки тайлов", info="Размер сетки тайлов NxN.", min=1, max=32, unit="px"),
    ] = 8


__all__ = ["ClaheParams"]
