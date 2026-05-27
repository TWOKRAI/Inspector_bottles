# -*- coding: utf-8 -*-
"""
Базовые фикстуры для тестов domain-слоя.

fixtures_dir      — путь к корню YAML-файлов проекта (корень multiprocess_prototype).
make_test_app_services() — builder для тестового AppServices (Task B.6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..app_services import AppServices
from ..protocols import (
    AuthFacade,
    CommandDispatcher,
    DisplayCatalog,
    EventBusProtocol,
    PluginCatalog,
    RecipeStore,
    RegistersBackend,
    ServiceCatalog,
    TopologyRepository,
)
from ._fakes import (
    FakeAuthFacade,
    FakeCommandDispatcher,
    FakeDisplayCatalog,
    FakeEventBus,
    FakePluginCatalog,
    FakeRecipeStore,
    FakeRegistersBackend,
    FakeServiceCatalog,
    FakeTopologyRepository,
)


@pytest.fixture
def fixtures_dir() -> Path:
    """Путь к корню multiprocess_prototype (содержит recipes/, backend/topology/)."""
    return Path(__file__).resolve().parent.parent.parent


def make_test_app_services(
    *,
    plugins: PluginCatalog | None = None,
    services: ServiceCatalog | None = None,
    displays: DisplayCatalog | None = None,
    recipes: RecipeStore | None = None,
    registers: RegistersBackend | None = None,
    topology: TopologyRepository | None = None,
    commands: CommandDispatcher | None = None,
    events: EventBusProtocol | None = None,
    auth: AuthFacade | None = None,
) -> AppServices:
    """Builder для тестового AppServices.

    Каждый None заменяется на in-memory Fake*-реализацию из _fakes.py.
    Это превентивная мера против MagicMock(spec=AppServices) паттерна
    из audit Inventory 6 (53 файла с ad-hoc мок-объектами).

    Тесту переопределить только нужное:
        svc = make_test_app_services(plugins=FakePluginCatalog({"blur"}))

    Запрет: новые тесты в domain/tests/ должны использовать ТОЛЬКО этот
    builder, не MagicMock и не голые dataclass-конструкторы AppServices.
    """
    return AppServices(
        plugins=plugins if plugins is not None else FakePluginCatalog(),
        services=services if services is not None else FakeServiceCatalog(),
        displays=displays if displays is not None else FakeDisplayCatalog(),
        recipes=recipes if recipes is not None else FakeRecipeStore(),
        registers=registers if registers is not None else FakeRegistersBackend(),
        topology=topology if topology is not None else FakeTopologyRepository(),
        commands=commands if commands is not None else FakeCommandDispatcher(),
        events=events if events is not None else FakeEventBus(),
        auth=auth if auth is not None else FakeAuthFacade(),
    )
