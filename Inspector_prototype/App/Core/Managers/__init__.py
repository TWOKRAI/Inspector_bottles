# -*- coding: utf-8 -*-
"""
Менеджеры для работы с данными приложения.
"""
from .converter_manager import ConverterManager
from .recipe_manager import RecipeManager
from .camera_manager import CameraManager
from .region_manager import RegionManager
from .data_manager import DataManager
from .logging_manager import LoggingManager
from .error_manager import ErrorManager
from .window_manager import WindowManager
from .translation_manager import TranslationManager

__all__ = [
    'ConverterManager',
    'RecipeManager',
    'CameraManager',
    'RegionManager',
    'DataManager',
    'LoggingManager',
    'ErrorManager',
    'WindowManager',
    'TranslationManager',
]
