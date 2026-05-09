"""Конфиг HikvisionCameraPlugin -- параметры Hikvision source-плагина."""
from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig


@register_schema("HikvisionCameraPluginConfigV1")
class HikvisionCameraConfig(PluginConfig):
    """Конфиг плагина Hikvision камеры.

    Hikvision-специализированный source plugin.
    SHM ring-buffer для zero-copy передачи кадров.
    """

    plugin_class: str = (
        "hikvision_camera_module_2.plugin.plugin.HikvisionCameraPlugin"
    )

    # Параметры камеры
    camera_id: Annotated[
        int,
        FieldMeta(description="ID камеры в системе (для SHM-имён)"),
    ] = 0

    camera_index: Annotated[
        int,
        FieldMeta(description="Индекс устройства Hikvision в списке enum_devices"),
    ] = 0

    resolution_width: Annotated[
        int,
        FieldMeta(description="Ширина кадра (px)"),
    ] = 1920

    resolution_height: Annotated[
        int,
        FieldMeta(description="Высота кадра (px)"),
    ] = 1080

    fps: Annotated[
        int,
        FieldMeta(description="Целевой FPS захвата"),
    ] = 25

    auto_start: Annotated[
        bool,
        FieldMeta(description="Автозапуск захвата при старте процесса"),
    ] = False

    # SHM ring-buffer
    ring_buffer_size: Annotated[
        int,
        FieldMeta(description="Количество слотов ring-buffer (K)"),
    ] = 3

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM layout: ring-buffer из K слотов для данной камеры.

        Имя слота формируется как hikvision_{camera_id}_frame,
        размерность — (height, width, 3) для BGR-кадра.
        """
        slot_name = f"hikvision_{self.camera_id}_frame"
        return {
            slot_name: (self.resolution_height, self.resolution_width, 3),
            "coll": self.ring_buffer_size,
        }
