# -*- coding: utf-8 -*-
"""
Регистры камеры Hikvision.
Поля заданы через общую схему полей регистров (поля добавляются по мере использования).
"""
from pydantic import BaseModel

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema
from App.Registers.models.field_registers.data_schema.field_schema import DEFAULT_FIELD_SCHEMA
from App.Registers.models.field_registers.data_schema.metadata_helper import RegisterMetadataHelper

field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)


class HikvisionRegisters(RegisterMetadataHelper, BaseModel):
    """Регистры камеры Hikvision"""
    pass
