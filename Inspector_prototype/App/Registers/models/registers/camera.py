# -*- coding: utf-8 -*-
"""
Регистры управления источником кадров (камера или файл изображения).
"""
from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
)


class CameraRegisters(RegisterBase):
    """Регистры управления камерой / источником кадров."""

    source: Annotated[
        str,
        FieldMeta(
            "Источник кадров",
            info="Источник входящих кадров: 'camera' — захват с камеры, 'image' — загрузка из файла.",
            routing={"channel": "control_camera"},
        ),
    ] = "camera"

    image_path: Annotated[
        str,
        FieldMeta(
            "Путь к изображению",
            info="Путь к файлу изображения (используется при source='image').",
            routing={"channel": "control_camera"},
        ),
    ] = "Data/last_frame.png"

    enable_main_processing: Annotated[
        bool,
        FieldMeta(
            "Главный выключатель обработки",
            info="Включает/отключает всю цепочку обработки изображений.",
            routing={"channel": "control_camera"},
        ),
    ] = True
