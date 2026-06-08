"""ColorConvertRegisters — режим конвертации (live-tunable выпадающим списком)."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)

# Все поддерживаемые режимы (Literal → выпадающий список в инспекторе ноды).
ColorMode = Literal[
    "none",
    "bgr2rgb",
    "rgb2bgr",
    "bgr2gray",
    "bgr2hsv",
    "bgr2hls",
    "bgr2lab",
    "bgr2luv",
    "bgr2yuv",
    "bgr2ycrcb",
    "bgr2xyz",
]


@register_schema("ColorConvertRegistersV1")
class ColorConvertRegisters(SchemaBase):
    """Режим конвертации цветовых каналов кадра."""

    mode: Annotated[
        ColorMode,
        FieldMeta("Режим", info="Цветовая конвертация кадра (live)"),
    ] = "bgr2rgb"
