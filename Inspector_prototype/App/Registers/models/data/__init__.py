# -*- coding: utf-8 -*-
"""
Модели данных для структур приложения (камеры, регионы, цепочки).
Эти модели описывают структуру данных, а не регистры управления.
"""
# Импортируем в правильном порядке для разрешения forward references
from .chain import ChainStepData
from .region import RegionData
from .camera import CameraData

# Обновляем forward references после импорта всех классов
# Pydantic 2 автоматически разрешает forward references при использовании строк
try:
    RegionData.model_rebuild()
    CameraData.model_rebuild()
except:
    pass

__all__ = [
    'ChainStepData',
    'RegionData',
    'CameraData',
]
