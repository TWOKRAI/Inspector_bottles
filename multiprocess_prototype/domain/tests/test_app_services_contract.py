# -*- coding: utf-8 -*-
"""
test_app_services_contract.py — тесты контракта AppServices (Task B.6).

Тестирует:
  - make_test_app_services() без аргументов → валидный AppServices
  - make_test_app_services(plugins=custom) подменяет только plugins
  - AppServices frozen (FrozenInstanceError при попытке записи)
  - AppServices slots (__dict__ отсутствует)
  - 9 полей с правильными именами
  - каждый Fake* удовлетворяет своему Protocol (assignment-проверка)
"""

from __future__ import annotations

import dataclasses

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
    ServiceManager,
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
    FakeServiceManager,
    FakeTopologyRepository,
)
from .conftest import make_test_app_services


# ==============================================================================
# test_make_test_app_services_no_args_returns_valid_appservices
# ==============================================================================


def test_make_test_app_services_no_args_returns_valid_appservices() -> None:
    """Builder без аргументов возвращает валидный AppServices с 9 не-None полями."""
    svc = make_test_app_services()

    assert isinstance(svc, AppServices)

    # Все 9 полей не None
    assert svc.plugins is not None
    assert svc.services is not None
    assert svc.displays is not None
    assert svc.recipes is not None
    assert svc.registers is not None
    assert svc.topology is not None
    assert svc.commands is not None
    assert svc.events is not None
    assert svc.auth is not None


# ==============================================================================
# test_make_test_app_services_override_plugins
# ==============================================================================


def test_make_test_app_services_override_plugins() -> None:
    """Передача custom plugin catalog подменяет только plugins; остальные — дефолтные."""
    custom_plugins = FakePluginCatalog(known={"blur", "edge"})
    svc = make_test_app_services(plugins=custom_plugins)

    # plugins — наш custom
    assert svc.plugins is custom_plugins

    # Остальные — дефолтные Fake-реализации (не None)
    assert isinstance(svc.services, FakeServiceManager)
    assert isinstance(svc.displays, FakeDisplayCatalog)
    assert isinstance(svc.recipes, FakeRecipeStore)
    assert isinstance(svc.registers, FakeRegistersBackend)
    assert isinstance(svc.topology, FakeTopologyRepository)
    assert isinstance(svc.commands, FakeCommandDispatcher)
    assert isinstance(svc.events, FakeEventBus)
    assert isinstance(svc.auth, FakeAuthFacade)


# ==============================================================================
# test_app_services_frozen
# ==============================================================================


def test_app_services_frozen() -> None:
    """Попытка svc.plugins = ... → FrozenInstanceError (frozen dataclass)."""
    svc = make_test_app_services()

    with pytest.raises(Exception):  # FrozenInstanceError / dataclasses.FrozenInstanceError
        svc.plugins = FakePluginCatalog()  # type: ignore[misc]


# ==============================================================================
# test_app_services_has_slots
# ==============================================================================


def test_app_services_has_slots() -> None:
    """AppServices использует __slots__ — __dict__ отсутствует."""
    svc = make_test_app_services()
    assert not hasattr(svc, "__dict__")


# ==============================================================================
# test_app_services_has_9_fields
# ==============================================================================


def test_app_services_has_9_fields() -> None:
    """AppServices содержит ровно 9 полей с правильными именами."""
    fields = dataclasses.fields(AppServices)
    assert len(fields) == 9

    field_names = {f.name for f in fields}
    expected = {
        "plugins",
        "services",
        "displays",
        "recipes",
        "registers",
        "topology",
        "commands",
        "events",
        "auth",
    }
    assert field_names == expected


# ==============================================================================
# test_each_fake_satisfies_protocol
# ==============================================================================


def test_each_fake_satisfies_protocol() -> None:
    """Каждый Fake* удовлетворяет соответствующему Protocol (assignment-тест).

    Это runtime-тест соответствия; статическая проверка в _fakes.py.
    Protocol'ы не runtime_checkable, поэтому проверяем через присваивание
    типизированным переменным (работает как type-check assertion).
    """
    # PluginCatalog
    plugins: PluginCatalog = FakePluginCatalog()
    assert plugins.list_plugins() == ()
    assert plugins.resolve("x") is None
    assert plugins.categories() == ("default",)

    # ServiceManager (+ backward-compat alias ServiceCatalog)
    services: ServiceManager = FakeServiceManager()
    assert services.list_services() == ()
    assert services.resolve("x") is None
    # Backward-compat: ServiceCatalog = ServiceManager
    services_alias: ServiceCatalog = FakeServiceCatalog()
    assert services_alias.list_services() == ()

    # DisplayCatalog
    displays: DisplayCatalog = FakeDisplayCatalog()
    assert displays.list_displays() == ()
    assert displays.resolve("x") is None

    # RecipeStore
    recipes: RecipeStore = FakeRecipeStore()
    assert recipes.list() == ()
    assert recipes.read("x") is None
    assert recipes.get_active() is None

    # RegistersBackend
    registers: RegistersBackend = FakeRegistersBackend()
    assert registers.get_field_specs("p", 0) == ()
    assert registers.get_value("p", 0, "f") is None

    # TopologyRepository
    topology: TopologyRepository = FakeTopologyRepository()
    loaded = topology.load()
    assert loaded is not None  # возвращает пустую Topology

    # CommandDispatcher
    commands: CommandDispatcher = FakeCommandDispatcher()
    assert isinstance(commands, FakeCommandDispatcher)

    # EventBusProtocol
    events: EventBusProtocol = FakeEventBus()
    assert isinstance(events, FakeEventBus)

    # AuthFacade
    auth: AuthFacade = FakeAuthFacade()
    assert auth.access_level == 0
    assert auth.is_authenticated() is False
    assert auth.has_permission("any_key") is True
