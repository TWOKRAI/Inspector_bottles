# -*- coding: utf-8 -*-
"""
Пакет дата-моделей приложения Inspector.

Дата-модели — чистые Pydantic BaseModel для хранения структурированных данных.
Экспортированы в __all__ для авто-дискавери:
    register_package_schemas("App.Registers.models.data", suffix="Data")
"""
from .chain import ChainStepData
from .region import RegionData
from .camera import CameraData

__all__ = [
    "ChainStepData",
    "RegionData",
    "CameraData",
]
