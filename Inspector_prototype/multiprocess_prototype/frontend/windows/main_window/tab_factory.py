# multiprocess_prototype/frontend/windows/main_window/tab_factory.py
"""Единая фабрика вкладок TabWidget для MainWindow и FrontendLauncher."""

from typing import Any, Callable, Dict, Optional

TabWidgetFactory = Callable[[str, dict], Any]


def create_tab_widget_factory(
    *,
    config: Dict[str, Any],
    registers_manager: Optional[Any] = None,
    camera_callbacks_map: Dict[str, Any],
    camera_type: str,
) -> TabWidgetFactory:
    from multiprocess_prototype.frontend.widgets import (
        CameraTabWidget,
        ProcessingTabWidget,
        RecipesTabWidget,
        SettingsTabWidget,
    )

    def factory(widget_key: str, tab_config: dict) -> Any:
        if widget_key == "recipes":
            return RecipesTabWidget(registers_manager=registers_manager)
        if widget_key == "settings":
            return SettingsTabWidget(
                registers_manager=registers_manager,
                ui=config.get("settings_tab"),
            )
        if widget_key == "processing":
            return ProcessingTabWidget(registers_manager=registers_manager)
        if widget_key == "camera":
            return CameraTabWidget(
                camera_type=camera_type,
                registers_manager=registers_manager,
                callbacks_map=camera_callbacks_map,
                ui=config.get("camera_tab"),
            )
        return None

    return factory
