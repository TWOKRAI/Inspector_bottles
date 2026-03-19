# multiprocess_prototype/frontend/widgets/__init__.py
"""Виджеты вкладок MainWindow."""

from .recipes_tab import RecipesTabWidget
from .settings_tab import SettingsTabWidget
from .processing_tab import ProcessingTabWidget
from .camera_tab import CameraTabWidget

__all__ = [
    "RecipesTabWidget",
    "SettingsTabWidget",
    "ProcessingTabWidget",
    "CameraTabWidget",
]
