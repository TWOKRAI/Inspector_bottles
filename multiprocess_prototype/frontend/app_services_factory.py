# -*- coding: utf-8 -*-
"""
frontend/app_services_factory.py — фабрика AppServices для run_gui().

Собирает 10 adapter'ов из Phase C в frozen AppServices dataclass.
Выделена из run_gui() для изолированного тестирования (Task D.1).

Алгоритм:
  1. register_domain_schemas() — lazy регистрация 8 domain entities (Q3).
  2. Создать QtEventBus (thread-safe wrapper над EventBus).
  3. Инстанцировать 10 adapter'ов из AppServicesDeps и других источников.
  4. Bootstrap ProjectHolder из текущей topology.
  5. Собрать CommandDispatcherOrchestrator (C.6).
  6. Вернуть готовый AppServices.

Failure: при ошибке инициализации adapter'а — пробрасывает RuntimeError.
run_gui() ловит его и вызывает sys.exit(1).

G.5.1: фабрика принимает explicit `AppServicesDeps` вместо `AppContext` —
снимает coupling factory→AppContext (предпосылка удаления AppContext в G.5.3).

Refs: plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md (Task D.1),
      plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.5.1)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from multiprocess_prototype.domain import (
    AppServices,
    Project,
    register_domain_schemas,
)
from multiprocess_prototype.domain.entities.project import ApplyContext
from multiprocess_prototype.adapters import (
    AuthFacadeFromAuthState,
    CommandDispatcherOrchestrator,
    ConfigStoreFromManager,
    DisplayCatalogFromRecipe,
    PluginCatalogFromRegistry,
    ProjectHolder,
    RecipeStoreFromManager,
    RegistersBackendFromManager,
    ServiceManagerFromRegistry,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.display_module import DisplayRegistry
    from multiprocess_framework.modules.registers_module import RegistersManager
    from multiprocess_framework.modules.service_module import ServiceRegistry
    from multiprocess_prototype.adapters import TopologyRepositoryStore
    from multiprocess_prototype.frontend.qt_event_bus import QtEventBus
    from multiprocess_prototype.frontend.state.auth_state import AuthState

logger = logging.getLogger(__name__)

# Путь к директории рецептов (convention, аналог 3g в app.py)
_RECIPES_DIR = Path(__file__).resolve().parent.parent / "recipes"


@dataclass(frozen=True)
class AppServicesDeps:
    """Explicit-контейнер зависимостей для build_app_services (G.5.1).

    Заменяет чтение `ctx.extras[...]` — фабрика больше не зависит от AppContext.
    app.py собирает этот контейнер из своих локальных переменных run_gui().

    Поля:
        event_bus: QtEventBus — публикует domain-события (создаётся рано в app.py).
        topology_store: TopologyRepositoryStore — источник истины topology (G.3).
        plugin_registry: PluginRegistry (класс) — read-only каталог плагинов.
        display_registry: DisplayRegistry singleton — каталог дисплеев.
        service_registry: ServiceRegistry — реестр сервисов.
        registers_manager: RegistersManager — live-регистры (FieldInfo + значения).
        config: dict — конфиг приложения (для ConfigStore).
        recipe_manager: RecipeManager | None — CRUD рецептов; None → fail-loud.
        auth_state: AuthState | None — auth-состояние; None → fail-loud.
    """

    event_bus: "QtEventBus"
    topology_store: "TopologyRepositoryStore"
    plugin_registry: Any
    display_registry: "DisplayRegistry"
    service_registry: "ServiceRegistry"
    registers_manager: "RegistersManager"
    config: dict = field(default_factory=dict)
    recipe_manager: Any = None
    auth_state: "AuthState | None" = None


def build_app_services(deps: AppServicesDeps) -> AppServices:
    """Собрать AppServices из explicit AppServicesDeps (G.5.1).

    Pre:
      - deps заполнен (event_bus, topology_store, plugin_registry,
        registers_manager, service_registry, display_registry,
        recipe_manager, auth_state).
      - QApplication создан (для QtEventBus, создаётся в app.py).

    Post:
      - Возвращает frozen AppServices с 10 не-None полями.

    Raises:
      RuntimeError: если adapter init или bootstrap провалился.
          run_gui() ловит и вызывает sys.exit(1).
    """
    # 1. Lazy регистрация domain schemas в SchemaRegistry (Q3 closed)
    register_domain_schemas()

    # 2. EventBus и TopologyRepositoryStore создаются рано в run_gui (app.py) —
    # store публикует TopologyReplaced на этот же bus (G.3).
    bus = deps.event_bus

    # 3. Adapter'ы

    # TopologyRepository: источник истины topology (владеет dict, публикует TopologyReplaced)
    topology_repo = deps.topology_store

    # PluginCatalog: read-only реестр плагинов
    plugins = PluginCatalogFromRegistry(deps.plugin_registry)

    # DisplayCatalog: recipe-scoped (Task 5.1 — источник истины = активный рецепт).
    # DisplayCatalogFromRecipe читает/пишет определения в секцию displays рецепта,
    # НЕ в глобальный displays.yaml. DisplayRegistry (framework singleton) остаётся
    # для runtime/preview SHM-метаданных (наполняется backend'ом в apply_topology).
    # Обратная совместимость: DisplayCatalogFromRegistry сохранён для runtime-нужд,
    # но в AppServices.displays подставляется recipe-scoped вариант.
    # DI: get_active_slug = lambda, чтобы не хардкодить доступ к RecipeManager singleton.

    # RecipeStore: CRUD-доступ к рецептам через RecipeManager
    recipe_manager = deps.recipe_manager
    if recipe_manager is not None:
        recipes = RecipeStoreFromManager(recipe_manager, _RECIPES_DIR)
    else:
        raise RuntimeError(
            "AppServices factory: recipe_manager отсутствует в AppServicesDeps. "
            "Проверьте инициализацию RecipeManager в run_gui() (шаг 3g)."
        )

    # DisplayCatalog (recipe-scoped): создаётся ПОСЛЕ recipes (зависит от RecipeStore).
    displays = DisplayCatalogFromRecipe(
        recipe_store=recipes,
        get_active_slug=recipes.get_active,
    )

    # ServiceManager: read + lifecycle управление сервисами
    services = ServiceManagerFromRegistry(deps.service_registry)

    # RegistersBackend: доступ к регистрам через TopologyRepository + PluginCatalog
    registers = RegistersBackendFromManager(
        deps.registers_manager,
        topology_repo,
        plugins,
    )

    # AuthFacade: read-only auth-состояние
    auth_state = deps.auth_state
    if auth_state is None:
        raise RuntimeError(
            "AppServices factory: auth_state отсутствует в AppServicesDeps. "
            "Проверьте инициализацию AuthState в run_gui() (шаг 3e)."
        )
    auth = AuthFacadeFromAuthState(auth_state)

    # ConfigStore: adapter поверх Config из config_module
    # В run_gui() нет отдельного Config backend — создаём из deps.config (dict).
    # Config принимает initial_data=dict и предоставляет get/set/data API.
    from multiprocess_framework.modules.config_module.core.config import Config as _ConfigBackend

    _config_backend = _ConfigBackend(initial_data=dict(deps.config))
    config = ConfigStoreFromManager(_config_backend)

    # 4. ProjectHolder bootstrap из текущей topology
    initial_topology = topology_repo.load()
    initial_project = Project.from_topology(initial_topology)
    project_holder = ProjectHolder(initial=initial_project)

    # 5. ApplyContext factory (динамический, новый каждый dispatch)
    def make_apply_context() -> ApplyContext:
        return ApplyContext(plugins=plugins, displays=displays, recipes=recipes)

    # 6. CommandDispatcherOrchestrator (Task C.6)
    commands = CommandDispatcherOrchestrator(
        project_holder=project_holder,
        topology_repo=topology_repo,
        event_bus=bus,
        apply_context_factory=make_apply_context,
    )

    # 7. Собрать AppServices (frozen dataclass, 10 полей)
    app_services = AppServices(
        plugins=plugins,
        services=services,
        displays=displays,
        recipes=recipes,
        registers=registers,
        topology=topology_repo,
        commands=commands,
        events=bus,
        auth=auth,
        config=config,
    )

    logger.info(
        "AppServices factory: создан успешно (10 полей, bus=%s)",
        type(bus).__name__,
    )

    return app_services


__all__ = ["build_app_services", "AppServicesDeps"]
