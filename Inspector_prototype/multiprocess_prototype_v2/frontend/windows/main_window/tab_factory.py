# multiprocess_prototype/frontend/windows/main_window/tab_factory.py
"""Единая фабрика вкладок TabWidget для MainWindow и FrontendLauncher."""

from typing import Any, Callable

from multiprocess_prototype_v2.frontend.app_context import FrontendAppContext

TabWidgetFactory = Callable[[str, dict], Any]


def create_tab_widget_factory(ctx: FrontendAppContext) -> TabWidgetFactory:
    """Собрать фабрику вкладок из явного контекста (config + регистры + рецепты + камера)."""
    from multiprocess_prototype_v2.frontend.widgets import (
        CameraTabWidget,
        CroppedRegionsTabWidget,
        PostProcessingTabWidget,
        ProcessingTabWidget,
        RecipesTabWidget,
        SettingsTabWidget,
    )

    registers_manager = ctx.registers_manager
    recipe_manager = ctx.recipe_manager
    camera_type = ctx.camera_type
    camera_callbacks_map = ctx.camera_callbacks_map

    tk = ctx.get_touch_keyboard()

    def factory(widget_key: str, tab_config: dict) -> Any:
        if widget_key == "recipes":
            return RecipesTabWidget(
                registers_manager=registers_manager,
                ui=ctx.get_recipes_tab_ui(),
                recipe_manager=recipe_manager,
                recipe_access=ctx.get_recipe_access(),
                touch_keyboard=tk,
            )
        if widget_key == "settings":
            return SettingsTabWidget(
                registers_manager=registers_manager,
                ui=ctx.get_settings_tab_ui(),
                recipe_manager=recipe_manager,
                recipe_access=ctx.get_recipe_access(),
                recipes_tab=ctx.get_recipes_tab_ui(),
                processing_tab_ui=ctx.get_processing_tab_ui(),
                touch_keyboard=tk,
            )
        if widget_key == "processing":
            return ProcessingTabWidget(
                registers_manager=registers_manager,
                touch_keyboard=tk,
            )
        if widget_key == "post_processing":
            return PostProcessingTabWidget(
                registers_manager=registers_manager,
                ui=ctx.get_post_processing_tab_ui(),
                touch_keyboard=tk,
            )
        if widget_key == "cropped_regions":
            return CroppedRegionsTabWidget(
                registers_manager=registers_manager,
                ui=ctx.get_cropped_regions_tab_ui(),
                touch_keyboard=tk,
            )
        if widget_key == "camera":
            return CameraTabWidget(
                camera_type=camera_type,
                registers_manager=registers_manager,
                callbacks_map=camera_callbacks_map,
                command_handler=ctx.command_handler,
                ui=ctx.get_camera_tab_ui(),
                touch_keyboard=tk,
            )
        return None

    return factory
