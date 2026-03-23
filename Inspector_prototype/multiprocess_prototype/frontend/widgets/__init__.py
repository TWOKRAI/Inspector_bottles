# multiprocess_prototype/frontend/widgets/
"""
Виджеты вкладок и прочие UI-пакеты.

Вкладки главного окна и полоса табов: widgets.tabs_setting (TabItemConfig, TabsConfig,
CameraTabWidget, …).
"""

from .tabs_setting import (
    CameraTabUiConfig,
    CameraTabWidget,
    ControlBinding,
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
    "CameraTabWidget",
    "build_camera_tab_callbacks",
    "CameraTabUiConfig",
    "TabItemConfig",
    "TabsConfig",
]
