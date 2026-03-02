# -*- coding: utf-8 -*-
"""
Регистры управления камерой.
Поля заданы через общую схему полей регистров.
"""
from pydantic import BaseModel

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema
from App.Registers.models.field_registers.data_schema import DEFAULT_FIELD_SCHEMA, RegisterMetadataHelper

field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)


class CameraRegisters(RegisterMetadataHelper, BaseModel):
    """Регистры управления камерой"""

    source: str = field_from_schema(
        'camera',
        description='Источник кадров',
        info='Источник кадров: camera или image',
    )
    image_path: str = field_from_schema(
        'Data/last_frame.png',
        description='Путь к изображению при source=image',
        info='Путь к изображению при source=image',
    )
    enable_main_processing: bool = field_from_schema(
        True,
        description='Главный выключатель обработки',
        info='Главный выключатель обработки',
    )
