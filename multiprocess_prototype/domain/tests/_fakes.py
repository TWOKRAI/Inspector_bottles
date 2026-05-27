# -*- coding: utf-8 -*-
"""
domain/tests/_fakes.py — 9 default in-memory реализаций Protocols (Task B.6).

Каждый класс — минимальная type-checked реализация соответствующего Protocol.
Никаких MagicMock — это даёт pyright-проверку сигнатур (audit Inventory 6 fix).

Используются в:
  - conftest.py::make_test_app_services() — builder для тестового AppServices
  - test_project_invariants.py — замена inline _FakePluginCatalog/_FakeDisplayCatalog
  - test_commands_apply.py — замена inline _FakePluginCatalog/_FakeDisplayCatalog
  - любых новых тестах Phase B–G (обязательный паттерн)

Импорт:
    from multiprocess_prototype.domain.tests._fakes import (
        FakePluginCatalog, FakeServiceCatalog, FakeDisplayCatalog,
        FakeRecipeStore, FakeRegistersBackend, FakeTopologyRepository,
        FakeCommandDispatcher, FakeEventBus, FakeAuthFacade,
    )
"""

from __future__ import annotations

from typing import Any

from ..commands import ProjectCommand
from ..entities import Recipe, Topology
from ..events import ProjectEvent
from ..protocols import (
    AuthFacade,
    CommandDispatcher,
    DisplayCatalog,
    DisplaySpec,
    EventBusProtocol,
    FieldSpec,
    PluginCatalog,
    PluginSpec,
    RecipeStore,
    RegistersBackend,
    ServiceCatalog,
    ServiceSpec,
    Subscription,
    TopologyRepository,
)


# ==============================================================================
# FakePluginCatalog
# ==============================================================================


class FakePluginCatalog:
    """In-memory PluginCatalog с настраиваемым набором известных плагинов.

    По умолчанию — пустой каталог (no known plugins).
    """

    def __init__(self, known: set[str] | None = None) -> None:
        self._known: set[str] = known or set()

    def list_plugins(self) -> tuple[PluginSpec, ...]:
        return tuple(PluginSpec(name=n, category="default") for n in sorted(self._known))

    def resolve(self, plugin_name: str) -> PluginSpec | None:
        if plugin_name in self._known:
            return PluginSpec(name=plugin_name, category="default")
        return None

    def categories(self) -> tuple[str, ...]:
        return ("default",)


# Явное объявление соответствия Protocol для статического контроля
_: PluginCatalog = FakePluginCatalog()
del _


# ==============================================================================
# FakeServiceCatalog
# ==============================================================================


class FakeServiceCatalog:
    """In-memory ServiceCatalog с настраиваемым набором известных сервисов."""

    def __init__(self, known: set[str] | None = None) -> None:
        self._known: set[str] = known or set()

    def list_services(self) -> tuple[ServiceSpec, ...]:
        return tuple(ServiceSpec(service_id=s, display_name=s) for s in sorted(self._known))

    def resolve(self, service_id: str) -> ServiceSpec | None:
        if service_id in self._known:
            return ServiceSpec(service_id=service_id, display_name=service_id)
        return None


_s: ServiceCatalog = FakeServiceCatalog()
del _s


# ==============================================================================
# FakeDisplayCatalog
# ==============================================================================


class FakeDisplayCatalog:
    """In-memory DisplayCatalog с настраиваемым набором известных дисплеев."""

    def __init__(self, known: set[str] | None = None) -> None:
        self._known: set[str] = known or set()

    def list_displays(self) -> tuple[DisplaySpec, ...]:
        return tuple(DisplaySpec(display_id=d, display_name=d) for d in sorted(self._known))

    def resolve(self, display_id: str) -> DisplaySpec | None:
        if display_id in self._known:
            return DisplaySpec(display_id=display_id, display_name=display_id)
        return None


_d: DisplayCatalog = FakeDisplayCatalog()
del _d


# ==============================================================================
# FakeRecipeStore
# ==============================================================================


class FakeRecipeStore:
    """In-memory RecipeStore. dict[slug, Recipe], get_active/set_active."""

    def __init__(
        self,
        recipes: dict[str, Recipe] | None = None,
        active: str | None = None,
    ) -> None:
        self._data: dict[str, Recipe] = recipes or {}
        self._active: str | None = active

    def list(self) -> tuple[str, ...]:
        return tuple(self._data.keys())

    def read(self, slug: str) -> Recipe | None:
        return self._data.get(slug)

    def write(self, slug: str, recipe: Recipe) -> None:
        self._data[slug] = recipe

    def delete(self, slug: str) -> None:
        self._data.pop(slug, None)

    def get_active(self) -> str | None:
        return self._active

    def set_active(self, slug: str | None) -> None:
        self._active = slug


_r: RecipeStore = FakeRecipeStore()
del _r


# ==============================================================================
# FakeRegistersBackend
# ==============================================================================


class FakeRegistersBackend:
    """In-memory RegistersBackend. По умолчанию — нет полей, все значения None."""

    def get_field_specs(
        self,
        process_name: str,
        plugin_index: int,
    ) -> tuple[FieldSpec, ...]:
        return ()

    def get_value(
        self,
        process_name: str,
        plugin_index: int,
        field: str,
    ) -> Any:
        return None

    def set_value(
        self,
        process_name: str,
        plugin_index: int,
        field: str,
        value: Any,
    ) -> None:
        pass  # no-op


_rb: RegistersBackend = FakeRegistersBackend()
del _rb


# ==============================================================================
# FakeTopologyRepository
# ==============================================================================


class FakeTopologyRepository:
    """In-memory TopologyRepository. load/save работают с памятью."""

    def __init__(self, topology: Topology | None = None) -> None:
        self._topology: Topology = topology if topology is not None else Topology()

    def load(self) -> Topology:
        return self._topology

    def save(self, topology: Topology) -> None:
        self._topology = topology


_tr: TopologyRepository = FakeTopologyRepository()
del _tr


# ==============================================================================
# FakeCommandDispatcher
# ==============================================================================


class FakeCommandDispatcher:
    """In-memory CommandDispatcher. Хранит последнюю команду, возвращает []."""

    def __init__(self) -> None:
        self.last_command: ProjectCommand | None = None
        self.dispatched: list[ProjectCommand] = []

    def dispatch(self, command: ProjectCommand) -> list[ProjectEvent]:
        self.last_command = command
        self.dispatched.append(command)
        return []


_cd: CommandDispatcher = FakeCommandDispatcher()
del _cd


# ==============================================================================
# FakeSubscription (helper для FakeEventBus)
# ==============================================================================


class _FakeSubscription:
    """Минимальный Subscription для FakeEventBus."""

    def unsubscribe(self) -> None:
        pass  # no-op

    def __enter__(self) -> "_FakeSubscription":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.unsubscribe()


# ==============================================================================
# FakeEventBus
# ==============================================================================


class FakeEventBus:
    """In-memory EventBus для тестов, где AppServices.events нужен,
    но реальный EventBus не требуется.

    publish() — просто запоминает события; handlers не вызываются.
    subscribe() — возвращает no-op Subscription (не регистрирует handler).

    Для тестирования самого EventBus используй реальный EventBus из event_bus.py.
    """

    def __init__(self) -> None:
        self.published: list[ProjectEvent] = []

    def publish(self, event: ProjectEvent) -> None:
        self.published.append(event)

    def subscribe(
        self,
        event_type: type[Any],
        handler: Any,
    ) -> Subscription:
        return _FakeSubscription()  # type: ignore[return-value]


_eb: EventBusProtocol = FakeEventBus()
del _eb


# ==============================================================================
# FakeAuthFacade
# ==============================================================================


class FakeAuthFacade:
    """In-memory AuthFacade.

    По умолчанию: access_level=0, is_authenticated()=False, has_permission()=True.
    Настраивается через конструктор для тестов с разными уровнями доступа.
    """

    def __init__(
        self,
        access_level: int = 0,
        authenticated: bool = False,
        all_permissions: bool = True,
    ) -> None:
        self._access_level = access_level
        self._authenticated = authenticated
        self._all_permissions = all_permissions

    @property
    def access_level(self) -> int:
        return self._access_level

    def is_authenticated(self) -> bool:
        return self._authenticated

    def has_permission(self, key: str) -> bool:
        return self._all_permissions


_af: AuthFacade = FakeAuthFacade()
del _af


__all__ = [
    "FakePluginCatalog",
    "FakeServiceCatalog",
    "FakeDisplayCatalog",
    "FakeRecipeStore",
    "FakeRegistersBackend",
    "FakeTopologyRepository",
    "FakeCommandDispatcher",
    "FakeEventBus",
    "FakeAuthFacade",
]
