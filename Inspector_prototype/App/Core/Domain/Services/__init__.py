# -*- coding: utf-8 -*-
"""
Domain.Services — re-export из Core.Managers для совместимости с архитектурой.

Использование:
    from App.Core.Domain.Services.data_manager import DataManager
    from App.Core.Domain.Services import DataManager, CameraManager, ...
"""
from App.Core.Managers.data_manager import DataManager
from App.Core.Managers.camera_manager import CameraManager
from App.Core.Managers.region_manager import RegionManager
from App.Core.Managers.recipe_manager import RecipeManager
from App.Core.Managers.converter_manager import ConverterManager

__all__ = [
    'DataManager',
    'CameraManager',
    'RegionManager',
    'RecipeManager',
    'ConverterManager',
]
