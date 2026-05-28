# -*- coding: utf-8 -*-
"""
domain/tests/_fakes.py — 10 default in-memory реализаций Protocols (Task B.6, D.2b).

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
        FakeConfigStore,
    )
"""

from __future__ import annotations

import fnmatch
from typing import Any, Callable

from ..commands import ProjectCommand
from ..entities import Recipe, Topology
from ..events import ProjectEvent
from ..errors import DomainError
from ..protocols import (
    AuthFacade,
    CommandDispatcher,
    ConfigStore,
    DisplayCatalog,
    DisplaySpec,
    EventBusProtocol,
    FieldSpec,
    PluginCatalog,
    PluginSpec,
    RecipeStore,
    RegistersBackend,
    ServiceLifecycle,
    ServiceManager,
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

    Принимает:
    - known: set[str] — обратная совместимость (Phase B-E тесты).
    - specs: dict[str, PluginSpec] — полный контроль (Phase F+).
    """

    def __init__(
        self,
        known: set[str] | None = None,
        *,
        specs: dict[str, PluginSpec] | None = None,
    ) -> None:
        self._specs: dict[str, PluginSpec] = {}
        if specs is not None:
            self._specs = dict(specs)
        elif known is not None:
            self._specs = {n: PluginSpec(name=n, category="default") for n in known}

    def list_plugins(self) -> tuple[PluginSpec, ...]:
        return tuple(self._specs[k] for k in sorted(self._specs))

    def resolve(self, plugin_name: str) -> PluginSpec | None:
        return self._specs.get(plugin_name)

    def categories(self) -> tuple[str, ...]:
        cats = sorted({s.category for s in self._specs.values()}) or ["default"]
        return tuple(cats)


# Явное объявление соответствия Protocol для статического контроля
_: PluginCatalog = FakePluginCatalog()
del _


# ==============================================================================
# FakeServiceManager (бывший FakeServiceCatalog)
# ==============================================================================


class FakeServiceManager:
    """In-memory ServiceManager с настраиваемым набором известных сервисов.

    Поддерживает lifecycle: start/stop/restart/get_lifecycle.
    По умолчанию все сервисы в состоянии STOPPED.
    """

    def __init__(self, known: set[str] | None = None) -> None:
        self._known: set[str] = known or set()
        self._lifecycles: dict[str, ServiceLifecycle] = {s: ServiceLifecycle.STOPPED for s in self._known}

    def list_services(self) -> tuple[ServiceSpec, ...]:
        return tuple(ServiceSpec(service_id=s, display_name=s) for s in sorted(self._known))

    def resolve(self, service_id: str) -> ServiceSpec | None:
        if service_id in self._known:
            return ServiceSpec(service_id=service_id, display_name=service_id)
        return None

    def start(self, service_id: str) -> None:
        """Запускает сервис. Idempotent: если уже RUNNING — no-op."""
        if service_id not in self._known:
            raise DomainError(f"Unknown service: {service_id}")
        if self._lifecycles[service_id] == ServiceLifecycle.RUNNING:
            return  # idempotent no-op
        self._lifecycles[service_id] = ServiceLifecycle.RUNNING

    def stop(self, service_id: str) -> None:
        """Останавливает сервис. Idempotent: если уже STOPPED — no-op."""
        if service_id not in self._known:
            raise DomainError(f"Unknown service: {service_id}")
        if self._lifecycles[service_id] == ServiceLifecycle.STOPPED:
            return  # idempotent no-op
        self._lifecycles[service_id] = ServiceLifecycle.STOPPED

    def restart(self, service_id: str) -> None:
        """stop() + start()."""
        self.stop(service_id)
        self.start(service_id)

    def get_lifecycle(self, service_id: str) -> ServiceLifecycle:
        """Текущий lifecycle статус. Бросает DomainError если service_id неизвестен."""
        if service_id not in self._known:
            raise DomainError(f"Unknown service: {service_id}")
        return self._lifecycles[service_id]


# Backward-compatible alias
FakeServiceCatalog = FakeServiceManager

_s: ServiceManager = FakeServiceManager()
del _s


# ==============================================================================
# FakeDisplayCatalog
# ==============================================================================


class FakeDisplayCatalog:
    """In-memory DisplayCatalog (read+write CRUD store).

    Принимает начальный набор как:
    - dict[str, DisplaySpec] — полный контроль (Phase F)
    - set[str] — обратная совместимость с тестами Phase B-E (каждый id
      становится DisplaySpec с display_name=id и дефолтными конфигурационными полями)

    Оба варианта поддерживаются через единственный позиционный аргумент или
    keyword ``specs=`` / ``known=``.
    """

    def __init__(
        self,
        specs: dict[str, DisplaySpec] | set[str] | None = None,
        *,
        known: set[str] | None = None,
    ) -> None:
        self._specs: dict[str, DisplaySpec] = {}
        if specs is not None:
            if isinstance(specs, set):
                # Обратная совместимость: set[str] → dict[str, DisplaySpec]
                self._specs = {d: DisplaySpec(display_id=d, display_name=d) for d in specs}
            else:
                self._specs = dict(specs)
        elif known is not None:
            # Обратная совместимость через keyword: set[str] → dict[str, DisplaySpec]
            self._specs = {d: DisplaySpec(display_id=d, display_name=d) for d in known}

    def list_displays(self) -> tuple[DisplaySpec, ...]:
        return tuple(self._specs[k] for k in sorted(self._specs))

    def resolve(self, display_id: str) -> DisplaySpec | None:
        return self._specs.get(display_id)

    def register(self, spec: DisplaySpec) -> None:
        if spec.display_id in self._specs:
            raise ValueError(f"Display '{spec.display_id}' already registered")
        self._specs[spec.display_id] = spec

    def unregister(self, display_id: str) -> bool:
        return self._specs.pop(display_id, None) is not None

    def has(self, display_id: str) -> bool:
        return display_id in self._specs

    def persist(self) -> None:
        pass  # in-memory — no-op


_d: DisplayCatalog = FakeDisplayCatalog()
del _d


# ==============================================================================
# FakeRecipeStore
# ==============================================================================


class FakeRecipeStore:
    """In-memory RecipeStore (entity + raw dict).

    Поддерживает ОБА уровня доступа Protocol:
      - Recipe entity: dict[slug, Recipe] (read/write/list)
      - Raw dict: dict[slug, dict] (read_raw/save_raw)

    Phase F: + duplicate/deactivate, set_active -> bool.
    """

    def __init__(
        self,
        recipes: dict[str, Recipe] | None = None,
        active: str | None = None,
        raw: dict[str, dict] | None = None,
    ) -> None:
        self._data: dict[str, Recipe] = recipes or {}
        self._active: str | None = active
        self._raw: dict[str, dict] = raw or {}

    def list(self) -> tuple[str, ...]:
        # Объединяем slug'и из entity и raw хранилищ
        all_slugs = set(self._data.keys()) | set(self._raw.keys())
        return tuple(sorted(all_slugs))

    def read(self, slug: str) -> Recipe | None:
        return self._data.get(slug)

    def write(self, slug: str, recipe: Recipe) -> None:
        self._data[slug] = recipe

    def delete(self, slug: str) -> None:
        self._data.pop(slug, None)
        self._raw.pop(slug, None)

    def get_active(self) -> str | None:
        return self._active

    def set_active(self, slug: str | None) -> bool:
        """Установить активный рецепт. Вернуть True если slug есть в list или slug=None."""
        if slug is None:
            self._active = None
            return True
        all_slugs = set(self._data.keys()) | set(self._raw.keys())
        if slug not in all_slugs:
            return False
        self._active = slug
        return True

    def deactivate(self) -> None:
        """Сбросить активный рецепт."""
        self._active = None

    def duplicate(self, slug: str, new_slug: str) -> bool:
        """Дублировать рецепт. Если slug есть и new_slug нет — True; иначе False."""
        import copy

        all_slugs = set(self._data.keys()) | set(self._raw.keys())
        if slug not in all_slugs:
            return False
        if new_slug in all_slugs:
            return False
        # Копируем Recipe entity если есть
        if slug in self._data:
            self._data[new_slug] = copy.deepcopy(self._data[slug])
        # Копируем raw dict если есть
        if slug in self._raw:
            self._raw[new_slug] = copy.deepcopy(self._raw[slug])
        return True

    def read_raw(self, slug: str) -> dict | None:
        """Вернуть копию raw dict или None."""
        import copy

        raw = self._raw.get(slug)
        if raw is None:
            return None
        return copy.deepcopy(raw)

    def save_raw(self, slug: str, data: dict) -> None:
        """Сохранить копию raw dict."""
        import copy

        self._raw[slug] = copy.deepcopy(data)


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


# ==============================================================================
# FakeConfigStore
# ==============================================================================


class _FakeConfigSubscription:
    """Subscription-реализация для FakeConfigStore."""

    def __init__(self, subs: list, pair: tuple) -> None:
        self._subs = subs
        self._pair = pair

    def unsubscribe(self) -> None:
        """Удалить подписку. Повторный вызов — no-op."""
        if self._pair in self._subs:
            self._subs.remove(self._pair)

    def __enter__(self) -> "_FakeConfigSubscription":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.unsubscribe()


class FakeConfigStore:
    """In-memory ConfigStore для тестов. Satisfies ConfigStore Protocol.

    По умолчанию — пустое хранилище. Ключи в dot-notation.
    subscribe() поддерживает glob-паттерны (fnmatch).
    save() — no-op (in-memory).
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})
        self._subs: list[tuple[str, Callable[[str, Any], None]]] = []

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        for pattern, handler in list(self._subs):
            if fnmatch.fnmatch(key, pattern):
                handler(key, value)

    def get_section(self, section: str) -> dict[str, Any]:
        prefix = f"{section}."
        return {k[len(prefix) :]: v for k, v in self._data.items() if k.startswith(prefix)}

    def list_keys(self, prefix: str = "") -> tuple[str, ...]:
        return tuple(k for k in self._data if k.startswith(prefix))

    def subscribe(self, key_pattern: str, handler: Callable[[str, Any], None]) -> Subscription:
        pair: tuple[str, Callable[[str, Any], None]] = (key_pattern, handler)
        self._subs.append(pair)
        return _FakeConfigSubscription(self._subs, pair)  # type: ignore[return-value]

    def save(self) -> None:
        pass  # in-memory — no-op


_fc: ConfigStore = FakeConfigStore()
del _fc


__all__ = [
    "FakePluginCatalog",
    "FakeServiceManager",
    "FakeServiceCatalog",
    "FakeDisplayCatalog",
    "FakeRecipeStore",
    "FakeRegistersBackend",
    "FakeTopologyRepository",
    "FakeCommandDispatcher",
    "FakeEventBus",
    "FakeAuthFacade",
    "FakeConfigStore",
]
