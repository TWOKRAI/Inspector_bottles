"""Конфиг CapturePlugin — параметры захвата с вебкамеры."""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("CapturePluginConfigV2")
class CapturePluginConfig(PluginConfig):
    """Конфиг плагина захвата с вебкамеры.

    Самодостаточный source-плагин: cv2.VideoCapture → SHM ring-buffer → IPC.
    """

    plugin_class: str = (
        "Plugins.sources.capture.plugin.CapturePlugin"
    )

    # Параметры камеры
    camera_id: Annotated[
        int, FieldMeta(description="ID камеры в системе (для SHM-имён)")
    ] = 0
    device_id: Annotated[
        int, FieldMeta(description="Номер устройства cv2.VideoCapture")
    ] = 0
    fps: Annotated[
        int, FieldMeta(description="Целевой FPS захвата")
    ] = 25
    resolution_width: Annotated[
        int, FieldMeta(description="Ширина кадра (px)")
    ] = 640
    resolution_height: Annotated[
        int, FieldMeta(description="Высота кадра (px)")
    ] = 480

    # SHM ring-buffer
    ring_buffer_size: Annotated[
        int, FieldMeta(description="Количество слотов ring-buffer (K)")
    ] = 3

    # Routing: куда отправлять frame_ready
    frame_targets: Annotated[
        list[str] | None,
        FieldMeta(description="Список процессов-получателей кадров (None = processor_{camera_id})"),
    ] = None

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM layout: ring-buffer из K слотов для данной камеры."""
        slot_name = f"camera_{self.camera_id}_frame"
        return {
            slot_name: (self.resolution_height, self.resolution_width, 3),
            "coll": self.ring_buffer_size,
        }
