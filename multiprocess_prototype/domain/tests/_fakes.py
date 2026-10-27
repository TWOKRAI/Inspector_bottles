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

from multiprocess_framework.modules.recipe import RecipeConflict

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
    HistoryEntry,
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

    def update(self, spec: DisplaySpec) -> bool:
        """Обновить существующий дисплей in-place (по display_id).

        Зеркалит DisplayCatalogFromRecipe.update — сохраняет наличие записи,
        используется для toggle enabled. Возвращает False если дисплей не найден.
        """
        if spec.display_id not in self._specs:
            return False
        self._specs[spec.display_id] = spec
        return True

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
    Task 1.7 (C-30): ``rev`` повторяет протокол настоящего ``RecipeManager`` (1.1e):
      - ``rev`` — монотонный счётчик на весь стор (``delete`` его не сбрасывает: пересозданный рецепт
        не получает старый ``rev``);
      - запись с ``expected_rev`` сверяет его, несовпадение -> ``RecipeConflict`` (рецепта нет — current_rev None);
      - холостая запись (тело не изменилось) возвращает прежний ``rev``, изменяющая — новый;
      - ``save_layout``: рецепта нет и ``expected_rev=None`` -> ``None``; без blueprint -> текущий ``rev``;
        пустая раскладка, которой не было, не создаёт пустых коллекций; ``save_raw(layout=...)`` без
        blueprint -> ``ValueError``; раскладка пишется той же версией, что и данные;
      - ``expected_rev=None`` для существующего рецепта не проверяется (стор 1.1c подставляет ``rev``
        своего чтения; менеджер бросает ``ValueError``).
    Различия, о которых надо знать: ``read_canonical`` не нормализует — для рецепта, посеянного через
    ``raw=``, это форма файла, посеянного через ``recipes=`` — ``Recipe.to_dict()`` (форма модели);
    ``write()`` обновляет и сущность, и raw-тело (если оно есть), чтобы ``read_raw_with_rev`` не отдавал
    устаревшее тело при новом ``rev``.
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
        self._versions: dict[str, int] = {}
        self._counter = 0

    # --- ревизии (Task 1.7) ---

    def _next_version(self) -> int:
        self._counter += 1
        return self._counter

    def _current_rev(self, slug: str) -> str | None:
        """rev рецепта сейчас; ``None`` — рецепта нет. Посеянному рецепту версия выдаётся при первом обращении."""
        if slug not in self._data and slug not in self._raw:
            return None
        if slug not in self._versions:
            self._versions[slug] = self._next_version()
        return str(self._versions[slug])

    def _check_rev(self, slug: str, expected_rev: str | None) -> None:
        """``expected_rev=None`` — без проверки; иначе несовпадение -> ``RecipeConflict``."""
        if expected_rev is None:
            return
        current = self._current_rev(slug)
        if expected_rev != current:
            raise RecipeConflict(slug, expected_rev, current)

    def _commit(self, slug: str) -> str:
        """Новая версия рецепта (данные изменились); вернуть её rev."""
        self._versions[slug] = self._next_version()
        return str(self._versions[slug])

    def list(self) -> tuple[str, ...]:
        # Объединяем slug'и из entity и raw хранилищ
        all_slugs = set(self._data.keys()) | set(self._raw.keys())
        return tuple(sorted(all_slugs))

    def read(self, slug: str) -> Recipe | None:
        return self._data.get(slug)

    def write(self, slug: str, recipe: Recipe, *, expected_rev: str | None = None) -> str:
        self._check_rev(slug, expected_rev)
        current = self._current_rev(slug)
        new_raw = recipe.to_dict() if slug in self._raw else None
        if current is not None and self._data.get(slug) == recipe and (new_raw is None or self._raw[slug] == new_raw):
            return current  # холостая запись: тело не изменилось
        self._data[slug] = recipe
        if new_raw is not None:
            self._raw[slug] = new_raw
        return self._commit(slug)

    def delete(self, slug: str) -> None:
        self._data.pop(slug, None)
        self._raw.pop(slug, None)
        self._versions.pop(slug, None)  # счётчик стора монотонный: пересозданный рецепт получит новый rev

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

    def read_raw_with_rev(self, slug: str) -> tuple[dict | None, str | None]:
        """Вернуть ``(копия raw dict, rev)``; рецепта нет — ``(None, None)``."""
        raw = self.read_raw(slug)
        if raw is None:
            return None, None
        return raw, self._current_rev(slug)

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        """Вернуть ``(doc, rev)``: raw dict, а если его нет — ``Recipe.to_dict()`` сущности."""
        raw, rev = self.read_raw_with_rev(slug)
        if raw is not None:
            return raw, rev
        recipe = self._data.get(slug)
        if recipe is None:
            return None, None
        return recipe.to_dict(), self._current_rev(slug)

    def save_raw(
        self,
        slug: str,
        data: dict,
        *,
        expected_rev: str | None = None,
        layout: tuple[dict[str, list[float]], list[str]] | None = None,
    ) -> str:
        """Сохранить копию raw dict; ``layout`` — в ``blueprint.metadata`` той же версией."""
        import copy

        self._check_rev(slug, expected_rev)
        new_raw = copy.deepcopy(data)
        if layout is not None:
            if not isinstance(new_raw.get("blueprint"), dict):
                raise ValueError(f"раскладка рецепта '{slug}' требует blueprint-mapping в теле")
            self._put_layout(new_raw, *layout)
        current = self._current_rev(slug)
        if current is not None and self._raw.get(slug) == new_raw:
            return current  # холостая запись: тело не изменилось
        self._raw[slug] = new_raw
        return self._commit(slug)

    def save_layout(
        self,
        slug: str,
        positions: dict[str, list[float]],
        locked_nodes: list[str],
        *,
        expected_rev: str | None = None,
    ) -> str | None:
        """Точечно записать blueprint.metadata.{gui_positions,locked_nodes} в raw (как ``RecipeManager.save_layout``).

        Рецепта нет: ``expected_rev=None`` -> ``None``, иначе ``RecipeConflict``. Рецепт есть: сверка ``rev``;
        нет blueprint-mapping или раскладка не меняется -> текущий ``rev`` без записи; иначе новый ``rev``.
        """
        import copy

        current = self._current_rev(slug)
        if current is None:
            if expected_rev is not None:
                raise RecipeConflict(slug, expected_rev, None)
            return None
        self._check_rev(slug, expected_rev)
        raw = self._raw.get(slug)
        if not isinstance(raw, dict) or not isinstance(raw.get("blueprint"), dict):
            return current
        target = copy.deepcopy(raw)
        self._put_layout(target, positions, locked_nodes)
        if target == raw:
            return current
        self._raw[slug] = target
        return self._commit(slug)

    @staticmethod
    def _put_layout(raw: dict, positions: dict, locked_nodes: list) -> None:
        """Писатель раскладки (как ``RecipeManager._apply_layout``): пустую коллекцию, которой не было, не создаёт.

        Pre: ``raw["blueprint"]`` — mapping. Мутирует ``raw``.
        """
        import copy

        bp = raw["blueprint"]
        pos = copy.deepcopy(positions)
        locked = list(locked_nodes)
        meta = bp.get("metadata")
        if not isinstance(meta, dict):
            if not pos and not locked:
                return
            meta = {}
            bp["metadata"] = meta
        if pos or "gui_positions" in meta:
            meta["gui_positions"] = pos
        if locked or "locked_nodes" in meta:
            meta["locked_nodes"] = locked


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
    """In-memory CommandDispatcher. Хранит последнюю команду, возвращает [].

    G.4.1: undo/redo/history — no-op заглушки (fake не применяет команды и не
    держит снимков Project). Тесты, которым нужна реальная undo/redo-семантика,
    используют CommandDispatcherOrchestrator + ProjectHistory.
    """

    def __init__(self) -> None:
        self.last_command: ProjectCommand | None = None
        self.dispatched: list[ProjectCommand] = []
        # Реальный список, чтобы тесты могли проверить подписку/отписку слушателя.
        # Fake не делает undo, поэтому сам слушателей не вызывает.
        self.view_restore_listeners: list[Callable[[object], None]] = []

    def dispatch(
        self,
        command: ProjectCommand,
        *,
        coalesce_key: str | None = None,
        undoable: bool = True,
        view_state: Callable[[], object] | None = None,
    ) -> list[ProjectEvent]:
        self.last_command = command
        self.dispatched.append(command)
        return []

    def undo(self) -> bool:
        return False

    def redo(self) -> bool:
        return False

    def can_undo(self) -> bool:
        return False

    def can_redo(self) -> bool:
        return False

    def history(self, n: int = 20) -> list[HistoryEntry]:
        return []

    def clear_history(self) -> None:
        pass

    def add_change_callback(self, cb: Callable[[], None]) -> None:
        # G.4.4: fake не держит истории → нечего нотифицировать (no-op).
        pass

    def add_view_restore_listener(self, cb: Callable[[object], None]) -> None:
        if cb not in self.view_restore_listeners:
            self.view_restore_listeners.append(cb)

    def remove_view_restore_listener(self, cb: Callable[[object], None]) -> None:
        try:
            self.view_restore_listeners.remove(cb)
        except ValueError:
            pass


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

    on_access_changed сохраняет callback в self._access_callbacks — в тестах
    можно тригерить вручную: fake.trigger_access_changed().
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
        self._access_callbacks: list[Callable[[], None]] = []

    @property
    def access_level(self) -> int:
        return self._access_level

    def is_authenticated(self) -> bool:
        return self._authenticated

    def has_permission(self, key: str) -> bool:
        return self._all_permissions

    def on_access_changed(self, callback: Callable[[], None]) -> None:
        """Сохранить callback. Вызвать trigger_access_changed() для симуляции смены роли."""
        self._access_callbacks.append(callback)

    def trigger_access_changed(self) -> None:
        """Тест-помощник: вызвать все зарегистрированные callbacks (симуляция смены роли)."""
        for cb in list(self._access_callbacks):
            cb()


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
