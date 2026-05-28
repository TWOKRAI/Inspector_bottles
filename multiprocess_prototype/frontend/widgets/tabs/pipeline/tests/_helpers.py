# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для pipeline-тестов (Task E.1).

Предоставляет make_pipeline_services() — специализированный builder
поверх make_test_app_services(), добавляющий config с topology
и (опционально) bridge-атрибуты на Fake-объектах для legacy API.
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.tests._fakes import (
    FakeAuthFacade,
    FakeCommandDispatcher,
    FakeConfigStore,
    FakeDisplayCatalog,
    FakePluginCatalog,
    FakeRecipeStore,
    FakeRegistersBackend,
)
from multiprocess_prototype.domain.tests.conftest import make_test_app_services


_DEFAULT_TOPOLOGY = {
    "processes": [
        {"process_name": "camera", "plugins": [{"plugin_name": "capture"}]},
        {"process_name": "processor", "plugins": [{"plugin_name": "color_mask"}]},
    ],
    "wires": [
        {"source": "camera.capture.frame", "target": "processor.color_mask.frame"},
    ],
}


def make_pipeline_services(
    *,
    topology: dict[str, Any] | None = None,
    action_bus: Any = None,
    plugin_registry: Any = None,
    registers_manager: Any = None,
    recipe_manager: Any = None,
    display_registry: Any = None,
    config_extra: dict[str, Any] | None = None,
    auth: FakeAuthFacade | None = None,
) -> AppServices:
    """Создать AppServices для pipeline-тестов.

    Topology помещается в config под ключом "topology".
    Bridge-атрибуты (action_bus, _registry, _rm и т.д.) навешиваются
    на Fake-объекты через setattr для совместимости с legacy bridge
    в presenter и inspector.

    Args:
        topology: dict topology для config. По умолчанию — 2 процесса + 1 wire.
        action_bus: legacy ActionBus mock для undo/redo bridge.
        plugin_registry: raw _PluginRegistry для wire-валидации bridge.
        registers_manager: legacy RegistersManager для inspector bridge.
        recipe_manager: legacy RecipeManager для save/launch bridge.
        display_registry: legacy DisplayRegistry (если нужен _get_display_entries bridge).
        config_extra: дополнительные ключи для ConfigStore.
        auth: Fake AuthFacade (по умолчанию — all_permissions=True).
    """
    topo = topology if topology is not None else dict(_DEFAULT_TOPOLOGY)
    config_data: dict[str, Any] = {"topology": topo}
    if config_extra:
        config_data.update(config_extra)

    config = FakeConfigStore(initial=config_data)

    # Commands: навесить action_bus bridge если передан
    commands = FakeCommandDispatcher()
    if action_bus is not None:
        commands.action_bus = lambda: action_bus  # type: ignore[attr-defined]

    # Plugins: навесить _registry bridge для wire-валидации
    plugins = FakePluginCatalog()
    if plugin_registry is not None:
        plugins._registry = plugin_registry  # type: ignore[attr-defined]

    # Registers: навесить _rm bridge для inspector cards
    registers = FakeRegistersBackend()
    if registers_manager is not None:
        registers._rm = registers_manager  # type: ignore[attr-defined]

    # Recipes: навесить _rm bridge для save/launch
    recipes = FakeRecipeStore()
    if recipe_manager is not None:
        recipes._rm = recipe_manager  # type: ignore[attr-defined]

    # Displays: если нужен raw registry bridge
    displays = FakeDisplayCatalog()

    # Auth
    _auth = auth if auth is not None else FakeAuthFacade(all_permissions=True)

    return make_test_app_services(
        plugins=plugins,
        registers=registers,
        recipes=recipes,
        config=config,
        commands=commands,
        displays=displays,
        auth=_auth,
    )


__all__ = ["make_pipeline_services"]
