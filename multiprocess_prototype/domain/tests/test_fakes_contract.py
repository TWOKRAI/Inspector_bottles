# -*- coding: utf-8 -*-
"""
test_fakes_contract.py — параметризованный contract-тест «фейк реализует Protocol» (RS-6).

Контекст (docs/audits/2026-07-12_recipe-lifecycle-audit.md, класс A-1):
Кнопка «Сохранить» на вкладке Recipes падала ВСЕГДА, но тест это не ловил — тестовый
дублёр topology-store возвращал ``dict`` вместо ``Topology``-entity, контракт фейка
разошёлся с Protocol (``TopologyRepository.load() -> Topology``), и ``.get()`` на
dict-е «работал» в тесте, а на entity в проде падал ``AttributeError``. RS-1 (merge
``ad3c03ca``) починил конкретный фейк — этот файл закрывает класс СИСТЕМНО: любой
зарегистрированный фейк, чей метод возвращает не тот тип или не реализует метод
Protocol вовсе, ловится здесь, а не в проде.

Двухуровневая проверка на каждый метод/свойство Protocol:
  1. Структурная — фейк реализует член Protocol, обязательные параметры совпадают.
  2. Поведенческая — для членов, вызываемых без аргументов, фактический тип
     результата сверяется с return-аннотацией Protocol (именно это ловит A-1:
     isinstance-проверка по ``runtime_checkable`` Protocol саму по себе НЕ поймала
     бы «есть метод load(), но он возвращает dict» — nужен вызов + сверка типа).

Реестр (правило для новых фейков): каждый новый тестовый дублёр store/repository
ОБЯЗАН быть добавлен в ``FAKE_PROTOCOL_REGISTRY`` ниже одной строкой
``(label, fake_instance, ProtocolClass)``. Авто-скан модулей тестов на предмет
Fake*/Stub*/InMemory* сознательно не делается — у частичных ad-hoc дублёров (см.
аудит) разные конструкторы и области видимости (многие объявлены внутри тестовых
функций), автоматический скан был бы хрупким и создавал бы больше ложных
срабатываний, чем пользы. Явный реестр — «забытый» фейк не подсвечивается
статически, но каждый НОВЫЙ store/repository Protocol обязан завести здесь запись
по код-ревью (см. правило выше и docs/audits/2026-07-12_recipe-lifecycle-audit.md
п.4 целевой архитектуры).
"""

from __future__ import annotations

import inspect
import types
from pathlib import Path
from typing import Any, Callable, Protocol, Union, get_args, get_origin

import pytest

from ..entities import Process, PluginInstance, Recipe, RecipeMeta, Topology
from ..protocols import (
    AuthFacade,
    CommandDispatcher,
    ConfigStore,
    DisplayCatalog,
    EventBusProtocol,
    PluginCatalog,
    RecipeStore,
    RegistersBackend,
    ServiceManager,
    TopologyRepository,
)
from ._fakes import (
    FakeAuthFacade,
    FakeCommandDispatcher,
    FakeConfigStore,
    FakeDisplayCatalog,
    FakeEventBus,
    FakePluginCatalog,
    FakeRecipeStore,
    FakeRegistersBackend,
    FakeServiceManager,
    FakeTopologyRepository,
)

# Devices (RS-6, "минимум topology-store, displays, devices, recipes repositories"):
# RecipeDevicesStore.__init__ типизирует свою зависимость как `recipe_store: Any`
# (duck-typing, см. recipe_devices.py:29-31) — формального Protocol там нет. Реальный
# контракт — подмножество RecipeStore (read_raw/save_raw/get_active), задокументированное
# только докстрингом. Фиксируем его здесь как Protocol и переиспользуем РЕАЛЬНЫЙ ad-hoc
# фейк из devices-тестов (а не его копию), чтобы регресс в этом фейке тоже ловился.
from ...frontend.widgets.tabs.services.devices_common.tests.test_recipe_devices import (
    _FakeRecipeStore as _DevicesFakeRecipeStore,
)


class _RecipeDevicesBackingStore(Protocol):
    """Минимальный контракт, который ``RecipeDevicesStore`` реально использует.

    Зафиксирован здесь (а не в ``recipe_devices.py``) только для целей RS-6
    contract-теста — сам модуль продолжает принимать ``recipe_store: Any``.
    """

    def get_active(self) -> str | None: ...

    def read_raw(self, slug: str) -> dict | None: ...

    def save_raw(self, slug: str, data: dict) -> None: ...


# ==============================================================================
# Реестр (fake, Protocol) — единое место
# ==============================================================================


def _sample_topology() -> Topology:
    return Topology(processes=(Process(process_name="p1", plugins=(PluginInstance(plugin_name="blur", config={}),)),))


def _sample_recipe() -> Recipe:
    return Recipe(meta=RecipeMeta(name="demo", created_at="2026-01-01T00:00:00"), blueprint=Topology())


# Фабрики (не готовые инстансы) — RS-6/Fable-ревью находка 4: поведенческая
# проверка _assert_fake_matches_protocol ВЫЗЫВАЕТ zero-arg методы, включая
# мутаторы (deactivate/undo/redo/clear_history/persist/save). Общий module-level
# инстанс мутировался бы контрактной проверкой ОДНОГО фейка и мог повлиять на
# остальные тесты, использующие тот же объект. Каждый вызов фабрики — свежий
# инстанс; мутация внутри проверки безвредна, т.к. никто другой его не видит.
FAKE_PROTOCOL_REGISTRY: list[tuple[str, Callable[[], Any], type]] = [
    ("topology_repository", lambda: FakeTopologyRepository(_sample_topology()), TopologyRepository),
    ("recipe_store", lambda: FakeRecipeStore(recipes={"demo": _sample_recipe()}, active="demo"), RecipeStore),
    ("display_catalog", lambda: FakeDisplayCatalog(known={"main"}), DisplayCatalog),
    ("plugin_catalog", lambda: FakePluginCatalog(known={"blur"}), PluginCatalog),
    ("service_manager", lambda: FakeServiceManager(known={"cam"}), ServiceManager),
    ("registers_backend", FakeRegistersBackend, RegistersBackend),
    ("command_dispatcher", FakeCommandDispatcher, CommandDispatcher),
    ("event_bus", FakeEventBus, EventBusProtocol),
    ("auth_facade", lambda: FakeAuthFacade(access_level=2, authenticated=True), AuthFacade),
    ("config_store", lambda: FakeConfigStore({"a.b": 1}), ConfigStore),
    (
        "recipe_devices_backing_store",
        lambda: _DevicesFakeRecipeStore(Path("unused"), active="demo"),
        _RecipeDevicesBackingStore,
    ),
]


# ==============================================================================
# Механика проверки
# ==============================================================================


def _iter_protocol_members(protocol: type) -> list[tuple[str, str, Any]]:
    """Вернуть [(имя, вид, получатель-сигнатуры)] для публичных членов Protocol.

    вид: "method" | "property". Получатель — сама функция (method) либо fget
    (property) — передаётся в inspect.signature(eval_str=True) дальше.
    """
    members: list[tuple[str, str, Any]] = []
    for name, member in vars(protocol).items():
        if name.startswith("_"):
            continue
        if isinstance(member, property):
            if member.fget is not None:
                members.append((name, "property", member.fget))
        elif inspect.isfunction(member):
            members.append((name, "method", member))
    return members


def _type_matches(value: Any, annotation: Any) -> bool:
    """Сверить фактическое значение с Protocol return-аннотацией (best-effort).

    Явно обрабатывается: пустая/``Any`` аннотация (пропуск), ``None``/``NoneType``,
    ``X | Y`` / ``Union[X, Y]`` (рекурсивно по веткам), ``tuple[T, ...]``/``tuple[T]``
    (по элементам для гомогенного ``tuple[T, ...]``), ``list[T]`` (по элементам),
    ``dict[K, V]`` (ключи и значения по одному уровню), простой класс (``isinstance``).

    ЧЕСТНО НЕ проверяется (документированная дыра, не тихая — RS-6/Fable-ревью
    находка 5): ``Literal[...]`` (значения-константы), вложенные generic на глубину
    >1 (напр. ``dict[str, list[int]]`` — значения `dict` НЕ рекурсируются по своему
    `list[int]`), `TypedDict`, `Callable[...]` (сигнатура не сверяется), кастомные
    generic-классы без isinstance-совместимого origin. Для таких форм — best-effort
    `isinstance(value, origin)` (если origin — реальный класс) либо `True`
    (не блокируем tests на неразрешимой форме аннотации).
    """
    if annotation is inspect.Signature.empty or annotation is Any:
        return True
    if annotation is None:
        return value is None
    origin = get_origin(annotation)
    if origin is types.UnionType or origin is Union:
        return any(_type_matches(value, arg) for arg in get_args(annotation))
    if annotation is type(None):
        return value is None
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        args = get_args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_type_matches(item, args[0]) for item in value)
        return True
    if origin is list:
        if not isinstance(value, list):
            return False
        args = get_args(annotation)
        if args:
            return all(_type_matches(item, args[0]) for item in value)
        return True
    if origin is dict:
        if not isinstance(value, dict):
            return False
        args = get_args(annotation)
        if len(args) == 2:
            key_t, val_t = args
            return all(_type_matches(k, key_t) and _type_matches(v, val_t) for k, v in value.items())
        return True
    if origin is not None:
        try:
            return isinstance(value, origin)
        except TypeError:
            return True  # неразрешимый generic-origin (Literal/Callable/...) — не блокируем
    if isinstance(annotation, type):
        return isinstance(value, annotation)
    return True  # неизвестная форма аннотации — best effort, не блокируем


def _assert_fake_matches_protocol(label: str, fake: Any, protocol: type) -> None:
    """Ядро contract-теста: фейк реализует все члены Protocol структурно и поведенчески."""
    for name, kind, accessor in _iter_protocol_members(protocol):
        assert hasattr(fake, name), (
            f"{label}: фейк не реализует {protocol.__name__}.{name} "
            f"(регресс класса A-1 — контракт фейка разошёлся с Protocol)"
        )
        proto_sig = inspect.signature(accessor, eval_str=True)

        if kind == "property":
            value = getattr(fake, name)
            assert _type_matches(value, proto_sig.return_annotation), (
                f"{label}: {protocol.__name__}.{name} (property) вернуло "
                f"{type(value).__name__}, не соответствует аннотации {proto_sig.return_annotation!r}"
            )
            continue

        fake_member = getattr(fake, name)
        assert callable(fake_member), f"{label}: {protocol.__name__}.{name} не callable у фейка"

        fake_sig = inspect.signature(fake_member)
        proto_required = [
            p_name
            for p_name, p in proto_sig.parameters.items()
            if p_name != "self"
            and p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        fake_accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in fake_sig.parameters.values())
        missing = [p_name for p_name in proto_required if p_name not in fake_sig.parameters]
        assert not missing or fake_accepts_kwargs, (
            f"{label}: {protocol.__name__}.{name} — фейк не принимает обязательные параметры Protocol: {missing}"
        )

        # Поведенческая проверка (ловит класс A-1): если фейк вызываем без
        # аргументов, вызываем его и сверяем ФАКТИЧЕСКИЙ тип результата с
        # Protocol return-аннотацией. Наличие метода само по себе (структурная
        # проверка выше) баг A-1 не поймало бы — там load() у фейка ЕСТЬ,
        # но возвращает dict вместо Topology.
        fake_invocable_without_args = all(
            p.default is not inspect.Parameter.empty or p.kind == inspect.Parameter.VAR_KEYWORD
            for p in fake_sig.parameters.values()
        )
        if not proto_required and fake_invocable_without_args:
            result = fake_member()
            assert _type_matches(result, proto_sig.return_annotation), (
                f"{label}: {protocol.__name__}.{name}() вернул {type(result).__name__}, "
                f"не соответствует Protocol-аннотации {proto_sig.return_annotation!r} "
                f"(регресс класса A-1 — «фейк возвращает не тот тип»)"
            )


# ==============================================================================
# Параметризованный contract-тест
# ==============================================================================


@pytest.mark.parametrize(
    "label,make_fake,protocol",
    FAKE_PROTOCOL_REGISTRY,
    ids=[entry[0] for entry in FAKE_PROTOCOL_REGISTRY],
)
def test_fake_matches_protocol(label: str, make_fake: Callable[[], Any], protocol: type) -> None:
    """Каждый зарегистрированный фейк реализует свой Protocol (класс A-1 системно).

    ``make_fake()`` — свежий инстанс на КАЖДЫЙ запуск теста (не общий module-level
    объект): поведенческая проверка вызывает zero-arg методы, включая мутаторы
    (deactivate/undo/redo/clear_history/persist/save) — на свежем инстансе это
    безвредно (Fable-ревью находка 4).
    """
    _assert_fake_matches_protocol(label, make_fake(), protocol)


# ==============================================================================
# Негативные регресс-кейсы: contract-тест обязан ловить сломанные фейки
# ==============================================================================


class _BrokenTopologyRepositoryWrongReturnType:
    """Регресс-фикстура A-1: load() возвращает dict вместо Topology-entity."""

    def load(self) -> dict:  # type: ignore[override]
        return {}

    def save(self, topology: Topology) -> None:
        pass


def test_contract_catches_a1_style_wrong_return_type() -> None:
    """Негативный кейс: фейк, возвращающий dict вместо Topology (как в A-1), обязан упасть."""
    with pytest.raises(AssertionError):
        _assert_fake_matches_protocol(
            "broken_topology_repository_wrong_type",
            _BrokenTopologyRepositoryWrongReturnType(),
            TopologyRepository,
        )


class _BrokenTopologyRepositoryMissingMethod:
    """Регресс-фикстура: фейк не реализует save() — метод Protocol отсутствует вовсе."""

    def load(self) -> Topology:
        return Topology()


def test_contract_catches_missing_protocol_method() -> None:
    """Негативный кейс: фейк без одного из методов Protocol обязан упасть."""
    with pytest.raises(AssertionError):
        _assert_fake_matches_protocol(
            "broken_topology_repository_missing_save",
            _BrokenTopologyRepositoryMissingMethod(),
            TopologyRepository,
        )
