# -*- coding: utf-8 -*-
"""
Регистры процесса обработки кадров.
Поля заданы через общую схему полей регистров (поля добавляются по мере использования).
"""
from pydantic import BaseModel

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema
from App.Registers.models.field_registers.data_schema import DEFAULT_FIELD_SCHEMA, RegisterMetadataHelper

field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)


class FrameProcessRegisters(RegisterMetadataHelper, BaseModel):
    """Регистры процесса обработки кадров"""
    pass
