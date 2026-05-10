"""Конфиг CapturePlugin — параметры захвата с вебкамеры."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("CapturePluginConfigV1")
class CapturePluginConfig(PluginConfig):
    """Конфиг плагина захвата с вебкамеры.

    Самодостаточный — напрямую через cv2.VideoCapture.
    """

    plugin_class: str = (
        "multiprocess_prototype.backend.plugins.capture.plugin.CapturePlugin"
    )
    plugin_name: str = "capture"
    category: str = "source"

    # Параметры камеры
    camera_id: int = 0
    device_id: int = 0
    fps: int = 25
    resolution_width: int = 640
    resolution_height: int = 480

    # SHM ring-buffer
    ring_buffer_size: int = 3

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM layout: ring-buffer из K слотов для данной камеры."""
        slot_name = f"camera_{self.camera_id}_frame"
        return {
            slot_name: (self.resolution_height, self.resolution_width, 3),
            "coll": self.ring_buffer_size,
        }
