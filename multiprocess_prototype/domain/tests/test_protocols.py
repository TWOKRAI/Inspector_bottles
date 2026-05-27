# -*- coding: utf-8 -*-
"""
test_protocols.py — тесты Protocol-контрактов (Task B.5).

Для каждого из 9 Protocols определён минимальный in-memory _Fake<Protocol>,
после чего тест:
  1. Присваивает экземпляр переменной с типом Protocol (assignment-проверка).
  2. Вызывает методы и проверяет возвращаемые значения.

Тест test_all_protocols_exported проверяет, что все 9 Protocol-имён
доступны через публичный API multiprocess_prototype.domain.

In-memory fakes намеренно минимальны (5-10 строк) — полные stub-реализации
для builder make_test_app_services() создаются в Task B.6 (tests/_fakes.py).
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from multiprocess_prototype.domain.entities import Recipe, RecipeMeta, Topology
from multiprocess_prototype.domain.events import ProcessAdded, ProjectEvent
from multiprocess_prototype.domain.commands import AddProcess, ProjectCommand
from multiprocess_prototype.domain.protocols import (
    AuthFacade,
    CommandDispatcher,
    DisplayCatalog,
    DisplaySpec,
    EventBusProtocol,
    FieldSpec,
    PluginCatalog,
    PluginSpec,
    PortSpec,
    RecipeStore,
    RegistersBackend,
    ServiceCatalog,
    ServiceSpec,
    Subscription,
    TopologyRepository,
)
from multiprocess_prototype.domain.entities import PluginInstance, Process


# ==============================================================================
# test_plugin_catalog_protocol
# ==============================================================================


def test_plugin_catalog_protocol() -> None:
    """In-memory реализация PluginCatalog удовлетворяет Protocol."""

    class _FakeCatalog:
        def list_plugins(self) -> tuple[PluginSpec, ...]:
            return (PluginSpec(name="blur", category="processing"),)

        def resolve(self, plugin_name: str) -> PluginSpec | None:
            if plugin_name == "blur":
                return PluginSpec(name="blur", category="processing")
            return None

        def categories(self) -> tuple[str, ...]:
            return ("processing",)

    cat: PluginCatalog = _FakeCatalog()  # assignment-проверка
    assert len(cat.list_plugins()) == 1
    assert cat.resolve("blur") is not None
    assert cat.resolve("unknown") is None
    assert cat.categories() == ("processing",)


# ==============================================================================
# test_service_catalog_protocol
# ==============================================================================


def test_service_catalog_protocol() -> None:
    """In-memory реализация ServiceCatalog удовлетворяет Protocol."""

    class _FakeCatalog:
        def list_services(self) -> tuple[ServiceSpec, ...]:
            return (ServiceSpec(service_id="cam", display_name="Camera"),)

        def resolve(self, service_id: str) -> ServiceSpec | None:
            if service_id == "cam":
                return ServiceSpec(service_id="cam", display_name="Camera")
            return None

    svc: ServiceCatalog = _FakeCatalog()  # assignment-проверка
    assert len(svc.list_services()) == 1
    assert svc.resolve("cam") is not None
    assert svc.resolve("unknown") is None


# ==============================================================================
# test_display_catalog_protocol
# ==============================================================================


def test_display_catalog_protocol() -> None:
    """In-memory реализация DisplayCatalog удовлетворяет Protocol."""

    class _FakeCatalog:
        def list_displays(self) -> tuple[DisplaySpec, ...]:
            return (DisplaySpec(display_id="main", display_name="Main Output"),)

        def resolve(self, display_id: str) -> DisplaySpec | None:
            if display_id == "main":
                return DisplaySpec(display_id="main", display_name="Main Output")
            return None

    dsp: DisplayCatalog = _FakeCatalog()  # assignment-проверка
    assert len(dsp.list_displays()) == 1
    assert dsp.resolve("main") is not None
    assert dsp.resolve("unknown") is None


# ==============================================================================
# test_recipe_store_protocol
# ==============================================================================


def test_recipe_store_protocol() -> None:
    """In-memory реализация RecipeStore удовлетворяет Protocol."""

    class _FakeStore:
        def __init__(self) -> None:
            self._data: dict[str, Recipe] = {}
            self._active: str | None = None

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

    recipe = Recipe(
        meta=RecipeMeta(name="test", created_at="2026-01-01T00:00:00"),
        blueprint=Topology(),
    )
    store: RecipeStore = _FakeStore()  # assignment-проверка
    assert store.list() == ()
    store.write("test", recipe)
    assert store.list() == ("test",)
    assert store.read("test") == recipe
    assert store.get_active() is None
    store.set_active("test")
    assert store.get_active() == "test"
    store.delete("test")
    assert store.list() == ()


# ==============================================================================
# test_registers_backend_protocol
# ==============================================================================


def test_registers_backend_protocol() -> None:
    """In-memory реализация RegistersBackend удовлетворяет Protocol."""

    class _FakeBackend:
        def __init__(self) -> None:
            self._values: dict[tuple[str, int, str], Any] = {}

        def get_field_specs(self, process_name: str, plugin_index: int) -> tuple[FieldSpec, ...]:
            return (FieldSpec(name="threshold", dtype="int", label="Порог"),)

        def get_value(self, process_name: str, plugin_index: int, field: str) -> Any:
            return self._values.get((process_name, plugin_index, field))

        def set_value(self, process_name: str, plugin_index: int, field: str, value: Any) -> None:
            self._values[(process_name, plugin_index, field)] = value

    backend: RegistersBackend = _FakeBackend()  # assignment-проверка
    specs = backend.get_field_specs("proc", 0)
    assert len(specs) == 1
    assert specs[0].name == "threshold"
    backend.set_value("proc", 0, "threshold", 42)
    assert backend.get_value("proc", 0, "threshold") == 42


# ==============================================================================
# test_topology_repository_protocol
# ==============================================================================


def test_topology_repository_protocol() -> None:
    """In-memory реализация TopologyRepository удовлетворяет Protocol."""

    class _FakeRepository:
        def __init__(self) -> None:
            self._topology: Topology = Topology()

        def load(self) -> Topology:
            return self._topology

        def save(self, topology: Topology) -> None:
            self._topology = topology

    repo: TopologyRepository = _FakeRepository()  # assignment-проверка
    assert isinstance(repo.load(), Topology)
    new_topo = Topology(
        processes=(
            Process(
                process_name="p1",
                plugins=(PluginInstance(plugin_name="blur", config={}),),
            ),
        )
    )
    repo.save(new_topo)
    assert repo.load() == new_topo


# ==============================================================================
# test_command_dispatcher_protocol
# ==============================================================================


def test_command_dispatcher_protocol() -> None:
    """In-memory реализация CommandDispatcher удовлетворяет Protocol."""

    class _FakeDispatcher:
        def dispatch(self, command: ProjectCommand) -> list[ProjectEvent]:
            return []

    dispatcher: CommandDispatcher = _FakeDispatcher()  # assignment-проверка
    result = dispatcher.dispatch(AddProcess(process_name="proc"))
    assert result == []


# ==============================================================================
# test_event_bus_protocol
# ==============================================================================


def test_event_bus_protocol() -> None:
    """In-memory реализация EventBusProtocol и Subscription удовлетворяет Protocol."""

    class _FakeSubscription:
        def __init__(self) -> None:
            self.unsubscribed = False

        def unsubscribe(self) -> None:
            self.unsubscribed = True

        def __enter__(self) -> "_FakeSubscription":
            return self

        def __exit__(self, *exc_info: object) -> None:
            self.unsubscribe()

    class _FakeBus:
        def __init__(self) -> None:
            self._calls: list[ProjectEvent] = []

        def publish(self, event: ProjectEvent) -> None:
            self._calls.append(event)

        def subscribe(
            self,
            event_type: type[Any],
            handler: Callable[[Any], None],
        ) -> "_FakeSubscription":
            return _FakeSubscription()

    bus: EventBusProtocol = _FakeBus()  # assignment-проверка
    sub: Subscription = bus.subscribe(ProcessAdded, lambda e: None)
    assert not sub.unsubscribed  # type: ignore[union-attr]

    process = Process(process_name="p1", plugins=())
    event = ProcessAdded(process_name="p1", process=process)
    bus.publish(event)
    assert len(bus._calls) == 1  # type: ignore[union-attr]

    # context manager
    with bus.subscribe(ProcessAdded, lambda e: None) as s:
        pass
    assert s.unsubscribed  # type: ignore[union-attr]


# ==============================================================================
# test_auth_facade_protocol
# ==============================================================================


def test_auth_facade_protocol() -> None:
    """In-memory реализация AuthFacade удовлетворяет Protocol."""

    class _FakeAuth:
        @property
        def access_level(self) -> int:
            return 3

        def is_authenticated(self) -> bool:
            return True

        def has_permission(self, key: str) -> bool:
            return key in {"read", "write"}

    auth: AuthFacade = _FakeAuth()  # assignment-проверка
    assert auth.access_level == 3
    assert auth.is_authenticated() is True
    assert auth.has_permission("read") is True
    assert auth.has_permission("admin") is False


# ==============================================================================
# test_all_protocols_exported
# ==============================================================================


def test_all_protocols_exported() -> None:
    """Все 9 Protocol-имён и sidecar-dataclasses доступны из multiprocess_prototype.domain."""
    import multiprocess_prototype.domain as domain

    # 9 Protocols
    assert hasattr(domain, "PluginCatalog"), "PluginCatalog не экспортирован"
    assert hasattr(domain, "ServiceCatalog"), "ServiceCatalog не экспортирован"
    assert hasattr(domain, "DisplayCatalog"), "DisplayCatalog не экспортирован"
    assert hasattr(domain, "RecipeStore"), "RecipeStore не экспортирован"
    assert hasattr(domain, "RegistersBackend"), "RegistersBackend не экспортирован"
    assert hasattr(domain, "TopologyRepository"), "TopologyRepository не экспортирован"
    assert hasattr(domain, "CommandDispatcher"), "CommandDispatcher не экспортирован"
    assert hasattr(domain, "EventBusProtocol"), "EventBusProtocol не экспортирован"
    assert hasattr(domain, "AuthFacade"), "AuthFacade не экспортирован"

    # ServiceManager (Phase C.1.6) + backward-compat alias
    assert hasattr(domain, "ServiceManager"), "ServiceManager не экспортирован"
    assert domain.ServiceCatalog is domain.ServiceManager, "ServiceCatalog должен быть alias ServiceManager"
    assert hasattr(domain, "ServiceLifecycle"), "ServiceLifecycle не экспортирован"

    # Sidecar-dataclasses
    assert hasattr(domain, "PluginSpec"), "PluginSpec не экспортирован"
    assert hasattr(domain, "PortSpec"), "PortSpec не экспортирован"
    assert hasattr(domain, "ServiceSpec"), "ServiceSpec не экспортирован"
    assert hasattr(domain, "DisplaySpec"), "DisplaySpec не экспортирован"
    assert hasattr(domain, "FieldSpec"), "FieldSpec не экспортирован"
    assert hasattr(domain, "Subscription"), "Subscription не экспортирован"


# ==============================================================================
# test_sidecar_dataclasses_are_frozen
# ==============================================================================


def test_sidecar_dataclasses_are_frozen() -> None:
    """Все sidecar-dataclasses должны быть frozen (неизменяемы)."""
    port = PortSpec(name="input", dtype="frame")
    with pytest.raises((AttributeError, TypeError)):
        port.name = "other"  # type: ignore[misc]

    spec = PluginSpec(name="blur", category="processing")
    with pytest.raises((AttributeError, TypeError)):
        spec.name = "other"  # type: ignore[misc]

    svc = ServiceSpec(service_id="cam", display_name="Camera")
    with pytest.raises((AttributeError, TypeError)):
        svc.service_id = "other"  # type: ignore[misc]

    dsp = DisplaySpec(display_id="main", display_name="Main")
    with pytest.raises((AttributeError, TypeError)):
        dsp.display_id = "other"  # type: ignore[misc]

    fld = FieldSpec(name="threshold", dtype="int")
    with pytest.raises((AttributeError, TypeError)):
        fld.name = "other"  # type: ignore[misc]
