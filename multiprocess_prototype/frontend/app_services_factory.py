# -*- coding: utf-8 -*-
"""
frontend/app_services_factory.py — фабрика AppServices для run_gui().

Собирает 10 adapter'ов из Phase C в frozen AppServices dataclass.
Выделена из run_gui() для изолированного тестирования (Task D.1).

Алгоритм:
  1. register_domain_schemas() — lazy регистрация 8 domain entities (Q3).
  2. Создать QtEventBus (thread-safe wrapper над EventBus).
  3. Инстанцировать 10 adapter'ов из ctx.extras и других источников.
  4. Bootstrap ProjectHolder из текущей topology.
  5. Собрать CommandDispatcherOrchestrator (C.6).
  6. Вернуть готовый AppServices.

Failure: при ошибке инициализации adapter'а — пробрасывает RuntimeError.
run_gui() ловит его и вызывает sys.exit(1).

Refs: plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md (Task D.1)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

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
    DisplayCatalogFromRegistry,
    PluginCatalogFromRegistry,
    ProjectHolder,
    RecipeStoreFromManager,
    RegistersBackendFromManager,
    ServiceManagerFromRegistry,
    TopologyRepositoryFromHolder,
)
from multiprocess_prototype.frontend.qt_event_bus import QtEventBus

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

logger = logging.getLogger(__name__)

# Путь к директории рецептов (convention, аналог 3g в app.py)
_RECIPES_DIR = Path(__file__).resolve().parent.parent / "recipes"


def build_app_services(ctx: "AppContext") -> AppServices:
    """Собрать AppServices из заполнённого AppContext.

    Pre:
      - ctx.extras заполнен (plugin_registry, registers_manager,
        service_registry, display_registry, topology_holder,
        recipe_manager, auth_state).
      - QApplication создан (для QtEventBus).

    Post:
      - Возвращает frozen AppServices с 10 не-None полями.

    Raises:
      RuntimeError: если adapter init или bootstrap провалился.
          run_gui() ловит и вызывает sys.exit(1).
    """
    # 1. Lazy регистрация domain schemas в SchemaRegistry (Q3 closed)
    register_domain_schemas()

    # 2. Qt-aware EventBus (Task D.2)
    bus = QtEventBus()

    # 3. Adapter'ы — 10 штук

    # TopologyRepository: bidirectional bridge domain.Topology <-> TopologyHolder
    # peek_required/peek — тихое bridge-чтение: фабрика СТРОИТ AppServices из extras,
    # поэтому читает мигрированные ключи легитимно (Task F.7). Прямой ctx.extras[...]
    # из потребителей остаётся deprecated → error.
    topology_repo = TopologyRepositoryFromHolder(ctx.extras.peek_required("topology_holder"))

    # PluginCatalog: read-only реестр плагинов
    plugins = PluginCatalogFromRegistry(ctx.extras.peek_required("plugin_registry"))

    # DisplayCatalog: read+write реестр дисплеев (Phase F — writable store)
    _displays_yaml = Path("multiprocess_prototype/backend/config/displays.yaml")
    displays = DisplayCatalogFromRegistry(ctx.extras.peek_required("display_registry"), yaml_path=_displays_yaml)

    # RecipeStore: CRUD-доступ к рецептам через RecipeManager
    recipe_manager = ctx.extras.peek("recipe_manager")
    if recipe_manager is not None:
        recipes = RecipeStoreFromManager(recipe_manager, _RECIPES_DIR)
    else:
        raise RuntimeError(
            "AppServices factory: recipe_manager отсутствует в ctx.extras. "
            "Проверьте инициализацию RecipeManager в run_gui() (шаг 3g)."
        )

    # ServiceManager: read + lifecycle управление сервисами
    services = ServiceManagerFromRegistry(ctx.extras.peek_required("service_registry"))

    # RegistersBackend: доступ к регистрам через TopologyRepository + PluginCatalog
    registers = RegistersBackendFromManager(
        ctx.extras.peek_required("registers_manager"),
        topology_repo,
        plugins,
    )

    # AuthFacade: read-only auth-состояние
    auth_state = ctx.extras.peek("auth_state")
    if auth_state is None:
        raise RuntimeError(
            "AppServices factory: auth_state отсутствует в ctx.extras. "
            "Проверьте инициализацию AuthState в run_gui() (шаг 3e)."
        )
    auth = AuthFacadeFromAuthState(auth_state)

    # ConfigStore: adapter поверх Config из config_module
    # В run_gui() нет отдельного Config backend — создаём из ctx.config (dict).
    # Config принимает initial_data=dict и предоставляет get/set/data API.
    from multiprocess_framework.modules.config_module.core.config import Config as _ConfigBackend

    _config_backend = _ConfigBackend(initial_data=dict(ctx.config))
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


__all__ = ["build_app_services"]
