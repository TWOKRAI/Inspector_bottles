# multiprocess_prototype/frontend/widgets/
"""
Виджеты вкладок и прочие UI-пакеты.

Полоса табов: `tabs_setting` (TabItemConfig, TabsConfig, оболочки `recipes_tab/`, `recipes_settings_tab/`, …); реэкспорт
публичных классов вкладок — через `from .tabs_setting import …`.
"""

from .tabs_setting import (
    CameraTabUiConfig,
    CameraTabWidget,
    ControlBinding,
    CroppedRegionsTabUiConfig,
    CroppedRegionsTabWidget,
    PostProcessingTabUiConfig,
    PostProcessingTabWidget,
    ProcessingTabUiConfig,
    ProcessingTabWidget,
    RecipesTabConfig,
    RecipesTabWidget,
    SettingsTabConfig,
    SettingsTabWidget,
    TabItemConfig,
    TabsConfig,
    build_camera_tab_callbacks,
)

__all__ = [
    "RecipesTabWidget",
    "RecipesTabConfig",
    "SettingsTabWidget",
    "SettingsTabConfig",
    "ControlBinding",
    "ProcessingTabWidget",
    "ProcessingTabUiConfig",
    "CroppedRegionsTabUiConfig",
    "CroppedRegionsTabWidget",
    "PostProcessingTabWidget",
    "PostProcessingTabUiConfig",
    "CameraTabWidget",
    "build_camera_tab_callbacks",
    "CameraTabUiConfig",
    "TabItemConfig",
    "TabsConfig",
]
