"""Конфиг CameraServicePlugin — параметры multi-backend камеры."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.process_module.generic.generic_process_config import PluginConfig

CameraTypeStr = Literal["simulator", "webcam", "hikvision", "file"]


@register_schema("CameraServicePluginConfigV1")
class CameraServiceConfig(PluginConfig):
    """Конфиг плагина multi-backend камеры.

    Поддерживает 4 backend'а: simulator, webcam, hikvision, file.
    SHM ring-buffer для zero-copy передачи кадров.
    """

    plugin_class: str = (
        "Plugins.sources.camera_service.plugin.CameraServicePlugin"
    )

    # Тип backend'а
    camera_type: Annotated[
        CameraTypeStr,
        FieldMeta(description="Тип бэкенда камеры"),
    ] = "simulator"

    # Общие параметры
    camera_id: Annotated[
        int,
        FieldMeta(description="ID камеры в системе (для SHM-имён)"),
    ] = 0

    device_id: Annotated[
        int,
        FieldMeta(description="Номер устройства cv2.VideoCapture (webcam)"),
    ] = 0

    fps: Annotated[
        int,
        FieldMeta(description="Целевой FPS захвата"),
    ] = 25

    resolution_width: Annotated[
        int,
        FieldMeta(description="Ширина кадра (px)"),
    ] = 640

    resolution_height: Annotated[
        int,
        FieldMeta(description="Высота кадра (px)"),
    ] = 480

    auto_start: Annotated[
        bool,
        FieldMeta(description="Автозапуск захвата при старте процесса"),
    ] = False

    # Hikvision-специфичные
    camera_index: Annotated[
        int,
        FieldMeta(description="Индекс камеры Hikvision"),
    ] = 0

    hikvision_resolution_width: Annotated[
        int,
        FieldMeta(description="Ширина кадра Hikvision (px)"),
    ] = 1920

    hikvision_resolution_height: Annotated[
        int,
        FieldMeta(description="Высота кадра Hikvision (px)"),
    ] = 1080

    # Simulator-специфичные
    simulator_image_path: Annotated[
        str | None,
        FieldMeta(description="Путь к статическому изображению для симулятора"),
    ] = None

    # FileSource-специфичные
    file_source_path: Annotated[
        str,
        FieldMeta(description="Путь к видеофайлу"),
    ] = ""

    # SHM ring-buffer
    ring_buffer_size: Annotated[
        int,
        FieldMeta(description="Количество слотов ring-buffer (K)"),
    ] = 3

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM layout: ring-buffer из K слотов для данной камеры.

        Разрешение выбирается в зависимости от типа backend'а:
        hikvision — hikvision_resolution_*, остальные — resolution_*.
        """
        slot_name = f"camera_{self.camera_id}_frame"
        if self.camera_type == "hikvision":
            w = self.hikvision_resolution_width
            h = self.hikvision_resolution_height
        else:
            w = self.resolution_width
            h = self.resolution_height
        return {
            slot_name: (h, w, 3),
            "coll": self.ring_buffer_size,
        }
