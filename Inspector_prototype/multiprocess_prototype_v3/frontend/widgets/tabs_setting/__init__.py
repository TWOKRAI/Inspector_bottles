# multiprocess_prototype_v3/frontend/widgets/tabs_setting/
"""
Полоса вкладок: TabItemConfig, TabsConfig и оболочки (`recipes_tab/`, `recipes_settings_tab/`, `camera_tab/`, …).

Фиче-виджеты — соседние пакеты под `widgets` (`recipes_widget`, `cropped_regions_widget`, …).
"""

from .tab_item_config import TabItemConfig
from .tabs_config import TabsConfig

from .camera_tab import CameraTabUiConfig, CameraTabWidget, build_camera_tab_callbacks
from .cropped_regions_tab import CroppedRegionsTabUiConfig, CroppedRegionsTabWidget
from .post_processing_tab import PostProcessingTabUiConfig, PostProcessingTabWidget
from .processing_tab import ProcessingTabUiConfig, ProcessingTabWidget
from .recipes_tab import RecipesTabConfig, RecipesTabWidget
from .recipes_settings_tab import ControlBinding, SettingsTabConfig, SettingsTabWidget
from .display_tab import DisplayTabConfig, DisplayTabWidget

__all__ = [
    "TabItemConfig",
    "TabsConfig",
    "CameraTabWidget",
    "CameraTabUiConfig",
    "build_camera_tab_callbacks",
    "CroppedRegionsTabWidget",
    "CroppedRegionsTabUiConfig",
    "PostProcessingTabWidget",
    "PostProcessingTabUiConfig",
    "ProcessingTabWidget",
    "ProcessingTabUiConfig",
    "RecipesTabWidget",
    "RecipesTabConfig",
    "SettingsTabWidget",
    "SettingsTabConfig",
    "ControlBinding",
    "DisplayTabConfig",
    "DisplayTabWidget",
]
