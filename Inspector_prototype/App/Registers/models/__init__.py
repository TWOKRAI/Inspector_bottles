# -*- coding: utf-8 -*-
"""
Модели регистров для App Inspector.
Каждая модель находится в отдельном файле для лучшей организации кода.
"""
from .camera import CameraRegisters
from .processing import ProcessingRegisters
from .post_processing import PostProcessingRegisters
from .visual import VisualRegisters
from .draw import DrawRegisters
from .robot import RobotRegisters
from .conveyor import ConveyorRegisters
from .neuroun import NeurounRegisters
from .hikvision import HikvisionRegisters
from .frame_process import FrameProcessRegisters

__all__ = [
    'CameraRegisters',
    'ProcessingRegisters',
    'PostProcessingRegisters',
    'VisualRegisters',
    'DrawRegisters',
    'RobotRegisters',
    'ConveyorRegisters',
    'NeurounRegisters',
    'HikvisionRegisters',
    'FrameProcessRegisters',
]
