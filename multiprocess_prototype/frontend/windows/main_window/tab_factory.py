# multiprocess_prototype/frontend/windows/main_window/tab_factory.py
"""Единая фабрика вкладок TabWidget для MainWindow и FrontendLauncher."""

from collections.abc import Callable
from typing import Any

from multiprocess_prototype.frontend.app_context import FrontendAppContext

TabWidgetFactory = Callable[[str, dict], Any]


def create_tab_widget_factory(ctx: FrontendAppContext) -> TabWidgetFactory:
    """Собрать фабрику вкладок из явного контекста (config + регистры + рецепты + камера)."""
    from multiprocess_prototype.frontend.widgets import (
        DisplayTabWidget,
        RecipesTabWidget,
    )
    from multiprocess_prototype.frontend.widgets.settings.settings_tab import SettingsContainerWidget

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
                action_bus=ctx.action_bus,
            )
        if widget_key == "settings":
            return SettingsContainerWidget(
                registers_manager=registers_manager,
                ui=ctx.get_settings_tab_ui(),
                recipe_manager=recipe_manager,
                recipe_access=ctx.get_recipe_access(),
                recipes_tab=ctx.get_recipes_tab_ui(),
                processing_tab_ui=ctx.get_processing_tab_ui(),
                touch_keyboard=tk,
                settings_profile_manager=ctx.settings_profile_manager,
                action_bus=ctx.action_bus,
                theme_manager=ctx.extras.get("theme_manager"),
            )
        if widget_key == "sources":
            from multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab.widget import (
                SourcesTabWidget,
            )

            return SourcesTabWidget(
                camera_type=camera_type,
                registers_manager=registers_manager,
                callbacks_map=camera_callbacks_map,
                command_handler=ctx.command_handler,
                camera_tab_ui=ctx.get_camera_tab_ui(),
                post_processing_ui=ctx.get_post_processing_tab_ui(),
                touch_keyboard=tk,
                camera_registry=ctx.camera_registry,
                action_bus=ctx.action_bus,
                topology_editor=ctx.topology_editor,
                topology_bridge=ctx.topology_bridge,
            )
        if widget_key == "display":
            # Менеджеры display доступны через extras контекста
            window_manager = ctx.extras.get("window_manager")
            display_router = ctx.extras.get("display_router")
            camera_registry = ctx.camera_registry
            if window_manager is None or display_router is None or camera_registry is None:
                import logging

                logging.getLogger(__name__).warning(
                    "display tab: window_manager, display_router или camera_registry не переданы в ctx.extras"
                )
                return None
            return DisplayTabWidget(
                window_manager=window_manager,
                display_router=display_router,
                camera_registry=camera_registry,
                topology_editor=ctx.topology_editor,
                topology_bridge=ctx.topology_bridge,
            )
        if widget_key == "pipeline":
            from multiprocess_prototype.frontend.widgets.pipeline.pipeline_tab.widget import (
                PipelineTabWidget,
            )

            # Каталог загружается в launcher.py и передаётся через extras
            catalog = ctx.extras.get("processing_catalog", {}) or {}
            editor = ctx.topology_editor

            # known_processes_provider: берём из editor если доступен,
            # иначе fallback на extras["known_processes"] для backward compat
            if editor is not None:
                known_processes_provider = editor.process_names
            else:
                known_processes_provider = lambda: list(
                    ctx.extras.get("known_processes", []),
                )

            return PipelineTabWidget(
                action_bus=ctx.action_bus,
                catalog=catalog,
                region_id="default",
                known_processes_provider=known_processes_provider,
                known_displays_provider=lambda: list(
                    (
                        ctx.extras.get("window_manager")
                        and ctx.extras["window_manager"]._windows.keys()
                    )
                    or [],
                ),
                topology_editor=editor,
                topology_bridge=ctx.topology_bridge,
            )
        if widget_key == "processes":
            from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.widget import (
                ProcessesTabWidget,
            )
            return ProcessesTabWidget(
                command_handler=ctx.command_handler,
                topology_editor=ctx.topology_editor,
                topology_bridge=ctx.topology_bridge,
            )
        return None

    return factory
