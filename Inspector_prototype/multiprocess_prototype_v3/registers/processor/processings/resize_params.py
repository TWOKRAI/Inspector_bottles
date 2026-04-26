"""Параметры операции изменения размера кадра."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("ResizeParamsV3")
class ResizeParams(ProcessingParamsBase):
    """Параметры операции ресайза кадра."""

    type: Literal["resize"] = "resize"

    width: Annotated[
        int,
        FieldMeta("Ширина", info="Целевая ширина кадра.", min=16, max=8192, unit="px"),
    ] = 640

    height: Annotated[
        int,
        FieldMeta("Высота", info="Целевая высота кадра.", min=16, max=8192, unit="px"),
    ] = 480

    interpolation: Annotated[
        Literal["nearest", "linear", "cubic", "area"],
        FieldMeta("Интерполяция", info="cv2.INTER_* метод масштабирования."),
    ] = "linear"


__all__ = ["ResizeParams"]
