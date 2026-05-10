"""Конфиг RenderPlugin — параметры отрисовки."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("RenderPluginConfigV2")
class RenderPluginConfig(PluginConfig):
    """Конфиг плагина отрисовки.

    Output-плагин: читает кадр + маску из SHM → overlay → пишет результат в SHM.
    """

    plugin_class: str = (
        "multiprocess_prototype.plugins.rendering.renderer_service.plugin.RenderPlugin"
    )
    plugin_name: str = "render"
    category: str = "output"

    # Привязка к камере
    camera_id: int = 0

    # Прозрачность маски при наложении (0.0-1.0)
    mask_alpha: float = 0.5

    # Цвет маски (BGR)
    mask_color_b: int = 0
    mask_color_g: int = 255
    mask_color_r: int = 0

    # Размеры для output SHM
    resolution_width: int = 640
    resolution_height: int = 480

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM для финального результата (3 канала, BGR)."""
        return {
            f"render_{self.camera_id}": (self.resolution_height, self.resolution_width, 3),
            "coll": 1,
        }
