# multiprocess_prototype/frontend/widgets/tabs_setting/
"""
Полоса вкладок: TabItemConfig, TabsConfig и оболочки (`recipes_tab/`, `recipes_settings_tab/`, `camera_tab/`, …).

Фиче-виджеты — соседние пакеты под `widgets` (`recipes_widget`, `cropped_regions_widget`, …).
"""

from .tab_item_config import TabItemConfig
from .tabs_config import TabsConfig

from .sources_tab.camera_panel import CameraTabUiConfig, CameraTabWidget, build_camera_tab_callbacks
from .recipes_tab import RecipesTabConfig, RecipesTabWidget
from .recipes_settings_tab import ControlBinding, SettingsTabConfig, SettingsTabWidget
from .display_tab import DisplayTabConfig, DisplayTabWidget
__all__ = [
    "TabItemConfig",
    "TabsConfig",
    "CameraTabWidget",
    "CameraTabUiConfig",
    "build_camera_tab_callbacks",
    "RecipesTabWidget",
    "RecipesTabConfig",
    "SettingsTabWidget",
    "SettingsTabConfig",
    "ControlBinding",
    "DisplayTabConfig",
    "DisplayTabWidget",
]
