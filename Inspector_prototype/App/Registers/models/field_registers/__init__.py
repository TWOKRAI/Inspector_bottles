# -*- coding: utf-8 -*-
"""
Регистры приложения: схема полей и все модели *Registers.

Импорт схемы и хелпера метаданных:
  from App.Registers.models.field_registers import FieldSchema, DEFAULT_FIELD_SCHEMA, RegisterMetadataHelper

Импорт моделей регистров:
  from App.Registers.models.field_registers import DrawRegisters, CameraRegisters, ...
"""
from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema

from App.Registers.models.field_registers.data_schema import DEFAULT_FIELD_SCHEMA, RegisterMetadataHelper

from App.Registers.models.field_registers.draw import DrawRegisters
from App.Registers.models.field_registers.camera import CameraRegisters
from App.Registers.models.field_registers.processing import ProcessingRegisters
from App.Registers.models.field_registers.post_processing import PostProcessingRegisters
from App.Registers.models.field_registers.visual import VisualRegisters
from App.Registers.models.field_registers.robot import RobotRegisters
from App.Registers.models.field_registers.conveyor import ConveyorRegisters
from App.Registers.models.field_registers.neuroun import NeurounRegisters
from App.Registers.models.field_registers.hikvision import HikvisionRegisters
from App.Registers.models.field_registers.frame_process import FrameProcessRegisters

__all__ = [
    'FieldSchema',
    'DEFAULT_FIELD_SCHEMA',
    'RegisterMetadataHelper',
    'DrawRegisters',
    'CameraRegisters',
    'ProcessingRegisters',
    'PostProcessingRegisters',
    'VisualRegisters',
    'RobotRegisters',
    'ConveyorRegisters',
    'NeurounRegisters',
    'HikvisionRegisters',
    'FrameProcessRegisters',
]
