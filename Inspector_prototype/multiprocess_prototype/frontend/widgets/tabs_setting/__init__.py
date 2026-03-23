# multiprocess_prototype/frontend/widgets/tabs_setting/
"""
Вкладки главного окна: полоса (TabItemConfig, TabsConfig) и виджеты вкладок.

Подпакеты: camera_tab, processing_tab, recipes_tab, settings_tab.
"""

from .tab_item_config import TabItemConfig
from .tabs_config import TabsConfig

from .camera_tab import CameraTabUiConfig, CameraTabWidget, build_camera_tab_callbacks
from .processing_tab import ProcessingTabUiConfig, ProcessingTabWidget
from .recipes_tab import RecipesTabConfig, RecipesTabWidget
from .settings_tab import ControlBinding, SettingsTabConfig, SettingsTabWidget

__all__ = [
    "TabItemConfig",
    "TabsConfig",
    "CameraTabWidget",
    "CameraTabUiConfig",
    "build_camera_tab_callbacks",
    "ProcessingTabWidget",
    "ProcessingTabUiConfig",
    "RecipesTabWidget",
    "RecipesTabConfig",
    "SettingsTabWidget",
    "SettingsTabConfig",
    "ControlBinding",
]
