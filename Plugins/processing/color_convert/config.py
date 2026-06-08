"""Конфиг ColorConvertPlugin — режим конвертации каналов."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import PluginConfig
from multiprocess_framework.modules.process_module.plugins import register_schema

ColorModeStr = Literal["bgr2rgb", "rgb2bgr"]


@register_schema("ColorConvertPluginConfigV1")
class ColorConvertConfig(PluginConfig):
    """Конфиг плагина конвертации цветовых каналов.

    Оба режима выполняют один и тот же swap R/B — различие только семантическое
    (для читаемости рецепта).
    """

    plugin_class: str = "Plugins.processing.color_convert.plugin.ColorConvertPlugin"

    mode: Annotated[
        ColorModeStr,
        FieldMeta(description="Направление конвертации (оба = swap R/B)"),
    ] = "bgr2rgb"
