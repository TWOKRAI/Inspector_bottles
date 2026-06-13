"""Конфиг RoiCropPlugin — identity + register binding."""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginConfig,
    SchemaBase,
    register_schema,
)

from .registers import RoiCropRegisters


@register_schema("RoiCropPluginConfigV1")
class RoiCropConfig(PluginConfig):
    """Конфиг плагина выреза ROI — identity + register binding."""

    plugin_class: str = "Plugins.processing.roi_crop.plugin.RoiCropPlugin"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [RoiCropRegisters]
