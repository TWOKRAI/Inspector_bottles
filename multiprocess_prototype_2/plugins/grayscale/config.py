"""Конфиг GrayscalePlugin — параметры конвертации."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("GrayscalePluginConfigV2")
class GrayscalePluginConfig(PluginConfig):
    """Конфиг плагина grayscale.

    Простой processing: вход BGR → cv2.cvtColor → выход GRAY.
    """

    plugin_class: str = (
        "multiprocess_prototype_2.plugins.grayscale.plugin.GrayscalePlugin"
    )
    plugin_name: str = "grayscale"
    category: str = "processing"

    # Привязка к камере
    camera_id: int = 0

    # Размеры для output SHM
    resolution_width: int = 640
    resolution_height: int = 480

    # Куда отправлять результат
    target: str = "renderer"

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM для выходного grayscale (3 канала BGR для совместимости с stitcher)."""
        return {
            f"gray_{self.camera_id}": (self.resolution_height, self.resolution_width, 3),
            "coll": 1,
        }
