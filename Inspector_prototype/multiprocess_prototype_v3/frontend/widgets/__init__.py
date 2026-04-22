# multiprocess_prototype_v3/frontend/widgets/
"""
Виджеты вкладок и прочие UI-пакеты.

Полоса табов: `tabs_setting` (TabItemConfig, TabsConfig, оболочки `recipes_tab/`,
`recipes_settings_tab/`, …). Реэкспорт Qt-классов вкладок — **ленивый** (через
`__getattr__`), чтобы pure-Python тестам (напр. `recipes_widget/slot_combo_model`)
не требовать PyQt5 в окружении.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — только для type-checkers
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


_LAZY_NAMES = {
    "CameraTabUiConfig",
    "CameraTabWidget",
    "ControlBinding",
    "CroppedRegionsTabUiConfig",
    "CroppedRegionsTabWidget",
    "PostProcessingTabUiConfig",
    "PostProcessingTabWidget",
    "ProcessingTabUiConfig",
    "ProcessingTabWidget",
    "RecipesTabConfig",
    "RecipesTabWidget",
    "SettingsTabConfig",
    "SettingsTabWidget",
    "TabItemConfig",
    "TabsConfig",
    "build_camera_tab_callbacks",
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    mod = import_module(".tabs_setting", package=__name__)
    return getattr(mod, name)


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
