# -*- coding: utf-8 -*-
"""Вспомогательные фабрики для pipeline-тестов (Task E.1 -> F.4 -> G.2).

Предоставляет make_pipeline_services() — специализированный builder
поверх make_test_app_services(), добавляющий config с topology
и (опционально) bridge-атрибуты на Fake-объектах для legacy API.

Task F.4: recipe_manager больше не навешивается как _rm bridge.
Вместо этого FakeRecipeStore наполняется через raw-хранилище.
Task G.2: registers_manager — runtime-объект, НЕ на services. Передаётся через
make_pipeline_runtime()/RuntimeDeps или напрямую в PipelinePresenter/NodeInspectorPanel.
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.entities import Topology
from multiprocess_prototype.domain.protocols.plugin_catalog import PluginSpec
from multiprocess_prototype.domain.tests._fakes import (
    FakeAuthFacade,
    FakeCommandDispatcher,
    FakeConfigStore,
    FakeDisplayCatalog,
    FakePluginCatalog,
    FakeRecipeStore,
    FakeRegistersBackend,
    FakeTopologyRepository,
)
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps


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
    plugin_specs: "dict[str, PluginSpec] | None" = None,
    recipe_manager: Any = None,
    display_registry: Any = None,
    config_extra: dict[str, Any] | None = None,
    auth: FakeAuthFacade | None = None,
    events: Any = None,
) -> AppServices:
    """Создать AppServices для pipeline-тестов.

    Topology помещается в config под ключом "topology".
    Bridge-атрибуты (action_bus, _registry и т.д.) навешиваются
    на Fake-объекты через setattr для совместимости с legacy bridge
    в presenter и inspector.

    Task F.4: recipe_manager транслируется в FakeRecipeStore с raw-данными.
    Task F.5: plugin_specs (dict[str, PluginSpec]) заполняет FakePluginCatalog
    для wire-валидации через PluginCatalog Protocol (вместо raw _registry bridge).
    plugin_registry сохранён для sandbox-тестов (bridge by design).

    Args:
        topology: dict topology для config. По умолчанию -- 2 процесса + 1 wire.
        action_bus: legacy ActionBus mock для undo/redo bridge.
        plugin_registry: raw _PluginRegistry для sandbox bridge (by design).
        plugin_specs: dict[str, PluginSpec] для FakePluginCatalog (wire-валидация).
        recipe_manager: legacy RecipeManager (mock или реальный) для recipe-данных.
        display_registry: legacy DisplayRegistry.
        config_extra: дополнительные ключи для ConfigStore.
        auth: Fake AuthFacade (по умолчанию -- all_permissions=True).
        events: EventBus для проверки typed-подписок (G.1). По умолчанию --
            FakeEventBus (no-op publish); передай реальный EventBus для wiring-тестов.
    """
    topo = topology if topology is not None else dict(_DEFAULT_TOPOLOGY)
    config_data: dict[str, Any] = {"topology": topo}
    if config_extra:
        config_data.update(config_extra)

    config = FakeConfigStore(initial=config_data)

    # F.2b: presenter читает топологию из живого источника (services.topology),
    # поэтому TopologyRepository наполняется тем же dict, что и config.
    topology_repo = FakeTopologyRepository(Topology.from_dict(topo))

    # Commands: навесить action_bus bridge если передан
    commands = FakeCommandDispatcher()
    if action_bus is not None:
        commands.action_bus = lambda: action_bus  # type: ignore[attr-defined]

    # Plugins: F.5 — FakePluginCatalog с PluginSpec для wire-валидации через Protocol.
    # plugin_registry навешивается как _registry bridge для sandbox (by design).
    plugins = FakePluginCatalog(specs=plugin_specs) if plugin_specs else FakePluginCatalog()
    if plugin_registry is not None:
        plugins._registry = plugin_registry  # type: ignore[attr-defined]

    # Registers: domain RegistersBackend Protocol (value-семантика).
    # G.2: live RegistersManager (FieldInfo для inspector cards) НЕ здесь —
    # это runtime-объект, передаётся в PipelinePresenter/NodeInspectorPanel напрямую.
    registers = FakeRegistersBackend()

    # Recipes: Task F.4 -- строим FakeRecipeStore из recipe_manager данных
    recipes = _build_recipe_store(recipe_manager)

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
        topology=topology_repo,
        events=events,
    )


def _build_recipe_store(recipe_manager: Any) -> FakeRecipeStore:
    """Построить FakeRecipeStore из recipe_manager (mock или реальный).

    Стратегия:
    - recipe_manager=None -> пустой store.
    - recipe_manager с get_active/read_recipe -> наполняем raw из read_recipe.
    - Для реального RecipeManager: read_recipe возвращает dict из YAML.
    - Для MagicMock: read_recipe.return_value предустановлен в тесте.
    """
    if recipe_manager is None:
        return FakeRecipeStore()

    active: str | None = None
    raw: dict[str, dict] = {}

    # Извлекаем active slug
    if hasattr(recipe_manager, "get_active"):
        try:
            active = recipe_manager.get_active()
        except Exception:
            pass

    # Извлекаем raw recipe для active slug
    if active is not None and hasattr(recipe_manager, "read_recipe"):
        try:
            data = recipe_manager.read_recipe(active)
            if isinstance(data, dict):
                raw[active] = data
        except Exception:
            pass

    # Также поддерживаем recipes_dir (для реальных RecipeManager с YAML на диске)
    if hasattr(recipe_manager, "recipes_dir"):
        try:
            from pathlib import Path

            recipes_dir = Path(recipe_manager.recipes_dir)
            if recipes_dir.is_dir():
                import yaml

                for path in recipes_dir.glob("*.yaml"):
                    slug = path.stem
                    if slug not in raw:
                        try:
                            with open(path, encoding="utf-8") as f:
                                data = yaml.safe_load(f)
                            if isinstance(data, dict):
                                raw[slug] = data
                        except Exception:
                            pass
        except Exception:
            pass

    return FakeRecipeStore(raw=raw, active=active)


def make_pipeline_runtime(*, registers_manager: Any = None) -> RuntimeDeps:
    """Создать RuntimeDeps для pipeline tab-тестов (G.2).

    registers_manager — live RegistersManager (FieldInfo) для inspector-карточек.
    """
    return RuntimeDeps(registers_manager=registers_manager)


__all__ = ["make_pipeline_services", "make_pipeline_runtime"]
