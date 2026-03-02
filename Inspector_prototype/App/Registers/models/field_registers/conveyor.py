# -*- coding: utf-8 -*-
"""
Регистры управления конвейером.
Поля заданы через общую схему полей регистров (поля добавляются по мере использования).
"""
from pydantic import BaseModel

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema
from App.Registers.models.field_registers.data_schema import DEFAULT_FIELD_SCHEMA, RegisterMetadataHelper

field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)


class ConveyorRegisters(RegisterMetadataHelper, BaseModel):
    """Регистры управления конвейером"""
    pass
