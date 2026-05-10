"""Конфиг GrayscalePlugin — параметры конвертации."""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import PluginConfig


@register_schema("GrayscalePluginConfigV2")
class GrayscalePluginConfig(PluginConfig):
    """Конфиг плагина grayscale.

    Простой processing: вход BGR → cv2.cvtColor → выход GRAY.
    """

    plugin_class: str = (
        "Plugins.processing.grayscale.plugin.GrayscalePlugin"
    )

    # Привязка к камере
    camera_id: int = 0

    # Размеры кадра
    resolution_width: int = 640
    resolution_height: int = 480

    # Куда отправлять результат
    target: str = "renderer"
