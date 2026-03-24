# multiprocess_prototype/frontend/windows/main_window/tab_factory.py
"""Единая фабрика вкладок TabWidget для MainWindow и FrontendLauncher."""

from typing import Any, Callable

from multiprocess_prototype.frontend.app_context import FrontendAppContext

TabWidgetFactory = Callable[[str, dict], Any]


def create_tab_widget_factory(ctx: FrontendAppContext) -> TabWidgetFactory:
    """Собрать фабрику вкладок из явного контекста (config + регистры + рецепты + камера)."""
    from multiprocess_prototype.frontend.widgets import (
        CameraTabWidget,
        ProcessingTabWidget,
        RecipesTabWidget,
        SettingsTabWidget,
    )

    config = ctx.config
    registers_manager = ctx.registers_manager
    recipe_manager = ctx.recipe_manager
    camera_type = ctx.camera_type
    camera_callbacks_map = ctx.camera_callbacks_map

    def factory(widget_key: str, tab_config: dict) -> Any:
        if widget_key == "recipes":
            return RecipesTabWidget(
                registers_manager=registers_manager,
                ui=config.get("recipes_tab"),
                recipe_manager=recipe_manager,
                recipe_access=config.get("recipe_access"),
            )
        if widget_key == "settings":
            return SettingsTabWidget(
                registers_manager=registers_manager,
                ui=config.get("settings_tab"),
                recipe_manager=recipe_manager,
                recipe_access=config.get("recipe_access"),
                recipes_tab=config.get("recipes_tab"),
                processing_tab_ui=config.get("processing_tab_ui"),
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
