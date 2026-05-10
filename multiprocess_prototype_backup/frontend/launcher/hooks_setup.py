# multiprocess_prototype/frontend/launcher/hooks_setup.py
"""Доменная конфигурация: менеджеры, роутинг, контекст приложения."""
from pathlib import Path
from typing import Any

from multiprocess_prototype.backend.routing.throttle_middleware import FrameThrottleMiddleware
from multiprocess_prototype.frontend.actions.default_bus_factory import create_default_action_bus
from multiprocess_prototype.frontend.app_context import FrontendAppContext
from multiprocess_prototype.frontend.bridges.topology_bridge import TopologyBridge
from multiprocess_prototype.frontend.managers import RecipeManager, SettingsProfileManager
from multiprocess_prototype.frontend.managers.app_recipe_aggregate import (
    aggregate_to_snapshot,
    build_default_app_aggregate,
)
from multiprocess_prototype.frontend.managers.display_router import DisplayRouter
from multiprocess_prototype.frontend.managers.recipe_manager import DEFAULT_RECIPE_SLOT_ID
from multiprocess_prototype.frontend.managers.window_manager import DisplayWindowManager
from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor
from registers.processor.catalog.loader import load_catalog as _load_catalog

# Путь до каталога операций относительно пакета multiprocess_prototype
_CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "processing_catalog.yaml"


def build_domain_context(
    process: Any,
    config: dict[str, Any],
    regs: Any,
    cmd: Any,
    camera_callbacks_map: Any,
    camera_type: str,
    camera_registry: Any,
    app: Any,
    theme_manager: Any,
) -> tuple[FrontendAppContext, DisplayRouter, DisplayWindowManager, TopologyBridge]:
    """Собрать FrontendAppContext + Display-инфраструктуру.

    Returns:
        (app_ctx, display_router, window_manager_display, topology_bridge)
    """
    recipe_manager = _build_recipe_manager(config, regs)
    settings_profile_manager = _build_settings_manager(config, regs)

    throttle_mw = FrameThrottleMiddleware()
    display_enabled = config.get("display_enabled", True)
    display_router = DisplayRouter(
        router_manager=process.router_manager,
        memory_manager=process.memory_manager,
        throttle_middleware=throttle_mw,
        headless=not display_enabled,
    )
    window_manager_display = DisplayWindowManager(display_router)

    process._display_router = display_router
    process._window_manager_display = window_manager_display
    process._throttle_mw = throttle_mw

    processing_catalog = _load_catalog(_CATALOG_PATH)

    topology_editor = SystemTopologyEditor()
    topology_bridge = TopologyBridge(
        editor=topology_editor,
        command_handler=cmd,
        registers_manager=regs,
        window_manager=window_manager_display,
        display_router=display_router,
    )

    app_ctx = FrontendAppContext(
        config=config,
        registers_manager=regs,
        camera_callbacks_map=camera_callbacks_map,
        camera_type=camera_type,
        recipe_manager=recipe_manager,
        settings_profile_manager=settings_profile_manager,
        command_handler=cmd,
        camera_registry=camera_registry,
        action_bus=create_default_action_bus(regs),
        topology_editor=topology_editor,
        topology_bridge=topology_bridge,
        extras={
            "window_manager": window_manager_display,
            "display_router": display_router,
            "processing_catalog": processing_catalog,
            "theme_manager": theme_manager,
        },
    )

    return app_ctx, display_router, window_manager_display, topology_bridge


def _build_recipe_manager(config: dict[str, Any], regs: Any) -> RecipeManager:
    recipe_manager = RecipeManager(
        data_path=config.get("recipes_path"),
        app_recipes_path=config.get("settings_recipes_path"),
    )
    if regs is not None:
        recipe_manager.ensure_slot_from_registers(regs, DEFAULT_RECIPE_SLOT_ID)
    recipe_manager.ensure_app_slot_from_snapshot(
        DEFAULT_RECIPE_SLOT_ID,
        aggregate_to_snapshot(build_default_app_aggregate()),
    )
    return recipe_manager


def _build_settings_manager(config: dict[str, Any], regs: Any) -> SettingsProfileManager:
    settings_profile_manager = SettingsProfileManager(
        data_path=config.get("settings_profiles_path"),
    )
    if regs is not None:
        settings_profile_manager.ensure_default_profile(regs)
    return settings_profile_manager
