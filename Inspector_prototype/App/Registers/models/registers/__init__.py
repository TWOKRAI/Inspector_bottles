# -*- coding: utf-8 -*-
"""
Пакет регистров приложения Inspector.

Каждый модуль содержит один RegisterBase-класс.
Явный экспорт нужен чтобы App.Registers.models.__init__ мог делать
`from .registers import DrawRegisters, ...`
"""
from .camera import CameraRegisters
from .conveyor import ConveyorRegisters
from .draw import DrawRegisters
from .frame_process import FrameProcessRegisters
from .hikvision import HikvisionRegisters
from .neuroun import NeurounRegisters
from .post_processing import PostProcessingRegisters
from .processing import ProcessingRegisters
from .robot import RobotRegisters
from .visual import VisualRegisters

__all__ = [
    "CameraRegisters",
    "ConveyorRegisters",
    "DrawRegisters",
    "FrameProcessRegisters",
    "HikvisionRegisters",
    "NeurounRegisters",
    "PostProcessingRegisters",
    "ProcessingRegisters",
    "RobotRegisters",
    "VisualRegisters",
]
