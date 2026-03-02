# -*- coding: utf-8 -*-
"""
Регистры визуальных настроек.
Поля заданы через общую схему полей регистров.
"""
from pydantic import BaseModel

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema
from App.Registers.models.field_registers.data_schema import DEFAULT_FIELD_SCHEMA, RegisterMetadataHelper

field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)


class VisualRegisters(RegisterMetadataHelper, BaseModel):
    """Регистры визуальных настроек"""

    image_scale: float = field_from_schema(
        0.5,
        description='Масштаб изображения',
        info='Масштаб отображения изображения',
        min=0.1,
        max=2.0,
        range='0.1-2.0',
    )
