# multiprocess_prototype/frontend/widgets/
"""
Виджеты вкладок — пакеты «виджет + свой конфиг» рядом.

Общий слой списка вкладок: widgets.tabs (TabItemConfig, TabsConfig).
"""

from .camera_tab import CameraTabConfig, CameraTabUiConfig, CameraTabWidget
from .processing_tab import ProcessingTabConfig, ProcessingTabUiConfig, ProcessingTabWidget
from .recipes_tab import RecipesTabConfig, RecipesTabWidget
from .settings_tab import ControlBinding, SettingsTabConfig, SettingsTabWidget
from .tabs import TabItemConfig, TabsConfig

__all__ = [
    "RecipesTabWidget",
    "RecipesTabConfig",
    "SettingsTabWidget",
    "SettingsTabConfig",
    "ControlBinding",
    "ProcessingTabWidget",
    "ProcessingTabConfig",
    "ProcessingTabUiConfig",
    "CameraTabWidget",
    "CameraTabConfig",
    "CameraTabUiConfig",
    "TabItemConfig",
    "TabsConfig",
]
