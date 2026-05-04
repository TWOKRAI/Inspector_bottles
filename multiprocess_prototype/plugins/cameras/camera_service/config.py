"""Конфиг CameraServicePlugin — все параметры камеры."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("CameraServicePluginConfigV1")
class CameraServicePluginConfig(PluginConfig):
    """Конфиг плагина захвата камеры.

    Полнофункциональный source-плагин: поддерживает webcam, simulator,
    hikvision, file. 14 команд, StateProxy, SHM ring-buffer.
    """

    plugin_class: str = (
        "multiprocess_prototype.plugins.cameras.camera_service.plugin.CameraServicePlugin"
    )
    plugin_name: str = "capture"
    category: str = "source"

    # --- Идентификация камеры ---
    camera_id: int = 0
    camera_type: str = "simulator"

    # --- Ring-buffer (AD-6): количество SHM-слотов ---
    ring_buffer_size: int = 3

    # --- Общие параметры ---
    fps: int = 25
    resolution_width: int = 640
    resolution_height: int = 480

    # --- Динамическое разрешение SHM ---
    shm_native_resolution: bool = False

    # --- Webcam ---
    device_id: int = 0

    # --- Hikvision ---
    camera_index: int = 0
    hikvision_resolution_width: int = 1920
    hikvision_resolution_height: int = 1080
    hikvision_frame_rate: float = 25.0
    hikvision_exposure_time: float = 10000.0
    hikvision_gain: float = 0.0

    # --- File-source ---
    file_source_path: str = ""

    # --- Simulator ---
    use_simulator: bool = False
    simulator_image_path: str | None = None

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM layout: ring-buffer из K слотов для данной камеры."""
        slot_name = f"camera_{self.camera_id}_frame"
        return {
            slot_name: (self.resolution_height, self.resolution_width, 3),
            "coll": self.ring_buffer_size,
        }
