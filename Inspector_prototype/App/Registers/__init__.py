# -*- coding: utf-8 -*-
"""
Модуль регистров для App Inspector.
Используется Pydantic 2 для типизации и валидации данных.

Структура:
- models/ - отдельные файлы с моделями регистров
- manager.py - RegistersManager для управления всеми регистрами
- converters.py - RegistersConverter для конвертации в различные форматы
"""
# Экспорт всех моделей для обратной совместимости
from .models import (
    CameraRegisters,
    ProcessingRegisters,
    PostProcessingRegisters,
    VisualRegisters,
    DrawRegisters,
    RobotRegisters,
    ConveyorRegisters,
    NeurounRegisters,
    HikvisionRegisters,
    FrameProcessRegisters,
)

# Экспорт моделей данных
from .models.data import CameraData, RegionData, ChainStepData

# Экспорт менеджера и конвертера
from .manager import RegistersManager
from .converters import RegistersConverter

__all__ = [
    # Модели регистров управления
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
    # Модели данных
    'CameraData',
    'RegionData',
    'ChainStepData',
    # Менеджер и конвертер
    'RegistersManager',
    'RegistersConverter',
]
