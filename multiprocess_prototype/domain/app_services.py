# -*- coding: utf-8 -*-
"""
domain/app_services.py — типизированный DI-контейнер (Task B.6).

AppServices — frozen dataclass с 9 обязательными полями.
Все поля — Protocols (интерфейсы), никаких конкретных реализаций.
Никаких Optional / None / accessor-методов.

Domain ждёт полный набор. Деградированный режим (без части catalogs)
решается через Fake-реализации Protocols (см. tests/_fakes.py),
а не через опциональные поля — это предотвращает повторение паттерна
ctx.recipe_manager() -> None, который привёл к live-bug (hotfix 85eec097).

Реальная фабрика AppServices создаётся в Phase D в app.py:run_gui().
В Phase B AppServices существует только в тестах через make_test_app_services().
"""

from __future__ import annotations

from dataclasses import dataclass

from .protocols import (
    AuthFacade,
    CommandDispatcher,
    DisplayCatalog,
    EventBusProtocol,
    PluginCatalog,
    RecipeStore,
    RegistersBackend,
    ServiceManager,
    TopologyRepository,
)


@dataclass(frozen=True, slots=True)
class AppServices:
    """Типизированный DI-контейнер. 9 обязательных полей.

    Никаких Optional / None / accessor-методов. Domain ждёт полный набор.
    Тесты строят через make_test_app_services() из conftest.py — это
    превентивная мера против MagicMock(spec=...) паттерна из audit Inventory 6.

    Поля:
      plugins   — read-only реестр плагинов (PluginCatalog)
      services  — управление сервисами (ServiceManager: read + lifecycle)
      displays  — read-only реестр дисплеев (DisplayCatalog)
      recipes   — CRUD-доступ к рецептам (RecipeStore)
      registers — доступ к регистрам Inspector (RegistersBackend)
      topology  — persistence топологии (TopologyRepository)
      commands  — диспетчеризация команд (CommandDispatcher)
      events    — typed pub/sub шина событий (EventBusProtocol)
      auth      — read-only auth-состояние (AuthFacade)
    """

    plugins: PluginCatalog
    services: ServiceManager
    displays: DisplayCatalog
    recipes: RecipeStore
    registers: RegistersBackend
    topology: TopologyRepository
    commands: CommandDispatcher
    events: EventBusProtocol
    auth: AuthFacade


__all__ = [
    "AppServices",
]
