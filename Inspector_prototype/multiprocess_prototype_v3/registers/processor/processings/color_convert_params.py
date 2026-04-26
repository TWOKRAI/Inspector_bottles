"""Параметры операции преобразования цветового пространства."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("ColorConvertParamsV3")
class ColorConvertParams(ProcessingParamsBase):
    """Параметры операции конвертации цветового пространства."""

    type: Literal["color_convert"] = "color_convert"

    mode: Annotated[
        Literal["bgr2gray", "bgr2hsv", "bgr2rgb", "gray2bgr"],
        FieldMeta("Режим", info="Целевое преобразование цветовой схемы."),
    ] = "bgr2gray"


__all__ = ["ColorConvertParams"]
