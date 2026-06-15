"""Конфиг PhoneCameraPlugin — источник кадров «фото с телефона по WiFi»."""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import PluginConfig
from multiprocess_framework.modules.process_module.plugins import SchemaBase
from multiprocess_framework.modules.process_module.plugins import register_schema

from .registers import PhoneCameraRegisters


@register_schema("PhoneCameraPluginConfigV1")
class PhoneCameraConfig(PluginConfig):
    """Конфиг источника «телефон»: HTTP-сервер приёма фото + приём слова.

    Drop-in замена камеры: тот же выходной порт ``frame`` и SHM-слот
    ``camera_{camera_id}_frame``, что у camera_service — pipeline дальше не меняется.
    """

    plugin_class: str = "Services.phone_gateway.plugin.plugin.PhoneCameraPlugin"

    register_bindings: ClassVar[list[type[SchemaBase]]] = [PhoneCameraRegisters]

    camera_id: Annotated[
        int,
        FieldMeta(description="ID источника (для имён SHM-слотов)"),
    ] = 0

    host: Annotated[
        str,
        FieldMeta(description="Интерфейс прослушивания (0.0.0.0 = все сети)"),
    ] = "0.0.0.0"  # nosec B104 — приём с телефона по LAN, bind на все интерфейсы намеренно

    http_port: Annotated[
        int,
        FieldMeta(description="Порт HTTP-сервера, который открывают на телефоне"),
    ] = 8080

    resolution_width: Annotated[
        int,
        FieldMeta(description="Ширина кадра pipeline (px); фото вписывается letterbox"),
    ] = 640

    resolution_height: Annotated[
        int,
        FieldMeta(description="Высота кадра pipeline (px); фото вписывается letterbox"),
    ] = 480

    auto_start: Annotated[
        bool,
        FieldMeta(description="Поднять HTTP-сервер при старте процесса"),
    ] = True

    show_hint: Annotated[
        bool,
        FieldMeta(description="Показывать кадр-подсказку с адресом, пока нет фото"),
    ] = True

    ring_buffer_size: Annotated[
        int,
        FieldMeta(description="Количество слотов ring-buffer SHM (K)"),
    ] = 3

    wifi_ssid: Annotated[
        str,
        FieldMeta(description="SSID для QR подключения к WiFi (опционально)"),
    ] = ""

    wifi_password: Annotated[
        str,
        FieldMeta(description="Пароль WiFi для QR (опционально)", hidden=True),
    ] = ""

    @property
    def memory(self) -> dict[str, Any] | None:
        """SHM layout: ring-buffer из K слотов под кадр источника.

        Имя слота совместимо с camera_service (camera_{id}_frame), чтобы
        phone_camera был drop-in заменой камеры в рецепте.
        """
        slot_name = f"camera_{self.camera_id}_frame"
        return {
            slot_name: (self.resolution_height, self.resolution_width, 3),
            "coll": self.ring_buffer_size,
        }
