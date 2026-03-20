# multiprocess_prototype/frontend/windows/main_window/tab_factory.py
"""Единая фабрика вкладок TabWidget для MainWindow и FrontendLauncher."""

from typing import Any, Callable, Dict, Optional

TabWidgetFactory = Callable[[str, dict], Any]


def create_tab_widget_factory(
    *,
    config: Dict[str, Any],
    registers_manager: Optional[Any] = None,
    camera_callbacks: Dict[str, Any],
    processing_callbacks: Dict[str, Any],
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
            st_cfg = config.get("settings_tab", {})
            controls = st_cfg.get("controls", [])
            group_title = st_cfg.get("group_title", "Параметры отображения")
            return SettingsTabWidget(
                registers_manager=registers_manager,
                controls_config=controls,
                group_title=group_title,
            )
        if widget_key == "processing":
            return ProcessingTabWidget(
                registers_manager=registers_manager,
                callbacks=processing_callbacks,
            )
        if widget_key == "camera":
            return CameraTabWidget(
                camera_type=camera_type,
                callbacks=camera_callbacks,
            )
        return None

    return factory
