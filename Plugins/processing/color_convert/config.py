"""Конфиг ColorConvertPlugin — режим конвертации каналов."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import ColorConvertRegisters, ColorMode


@register_schema("ColorConvertPluginConfigV1")
class ColorConvertConfig(PluginConfig):
    """Конфиг плагина конвертации цветовых каналов.

    Режим — tunable (выпадающий список в инспекторе), хранится в register
    ColorConvertRegisters.mode; здесь дублируется для дефолта рецепта.
    """

    plugin_class: str = "Plugins.processing.color_convert.plugin.ColorConvertPlugin"

    # Привязка register-класса (mode как live-выпадающий список в инспекторе ноды).
    register_bindings: ClassVar[list[type[SchemaBase]]] = [ColorConvertRegisters]

    mode: ColorMode = "bgr2rgb"
