# -*- coding: utf-8 -*-
"""
adapters/tests/test_registers_backend.py — тесты для RegistersBackendFromManager.

Покрываемый класс:
    RegistersBackendFromManager (stores/registers_backend.py)

Паттерн изоляции:
    - FakeTopologyRepository / FakePluginCatalog — plain Python classes (не MagicMock).
    - FakeRegistersManager — минимальный fake RegistersManager.
      Реальный RegistersManager требует Pydantic-инстансов и IPC-callbacks,
      что делает unit-тест тяжёлым. Smoke-тест с реальным RegistersManager
      отложен на Phase E (требует полного окружения с register_classes).

Acceptance criteria (Task C.4):
    - [ ] Adapter satisfies Protocol RegistersBackend.
    - [ ] Mapping plugin_index → register_name работает.
    - [ ] Round-trip set/get.
    - [ ] DomainError на out-of-range / unknown process / unknown plugin.

Refs: plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md (Task C.4)
"""

from __future__ import annotations

from typing import Any

import pytest

from multiprocess_prototype.adapters.stores.registers_backend import RegistersBackendFromManager
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.protocols.plugin_catalog import PluginSpec
from multiprocess_prototype.domain.protocols.registers_backend import FieldSpec, RegistersBackend


# ==============================================================================
# Fake-классы для изоляции
# ==============================================================================


class _FakePluginCatalog:
    """Минимальный fake PluginCatalog.

    Хранит dict plugin_name → PluginSpec.
    Реализует Protocol PluginCatalog (list_plugins / resolve / categories).
    """

    def __init__(self, plugins: dict[str, PluginSpec]) -> None:
        self._plugins = plugins

    def list_plugins(self) -> tuple[PluginSpec, ...]:
        return tuple(self._plugins.values())

    def resolve(self, plugin_name: str) -> PluginSpec | None:
        return self._plugins.get(plugin_name)

    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({spec.category for spec in self._plugins.values()}))


class _FakeTopologyRepository:
    """Fake TopologyRepository, загружает Topology из dict.

    Реализует Protocol TopologyRepository (load / save).
    """

    def __init__(self, topology_dict: dict[str, Any]) -> None:
        from multiprocess_prototype.domain.entities.topology import Topology

        self._topology = Topology.from_dict(topology_dict)

    def load(self):  # -> Topology
        return self._topology

    def save(self, topology) -> None:
        self._topology = topology


class _FieldInfoLike:
    """Fake FieldInfo, имитирует структуру registers_module.core.field_info.FieldInfo."""

    def __init__(self, field_name: str, field_type: type = str) -> None:
        self.field_name = field_name
        self.field_type = field_type
        self.meta = None
        self.category = ""


class _FakeRegistersManager:
    """Минимальный fake для RegistersManager.

    Хранит данные в plain dict {register_name: {field: value}}.
    Реализует только методы, используемые RegistersBackendFromManager:
        - get_fields(register_name) → list[FieldInfoLike]
        - get_register(register_name) → _FakeRegister | None
        - set_field_value(register_name, field_name, value) → (bool, str|None)

    Smoke-тест с реальным RegistersManager отложен на Phase E:
        требует register_classes (Pydantic-модели) и отстройки build_rm_from_topology.
    """

    def __init__(
        self,
        registers: dict[str, dict[str, Any]] | None = None,
        fields_schema: dict[str, list[tuple[str, type]]] | None = None,
    ) -> None:
        """Инициализировать fake.

        Args:
            registers: {register_name: {field_name: value}} — начальные данные.
            fields_schema: {register_name: [(field_name, field_type), ...]} — схема полей.
                           Используется в get_fields(). Если None — пустая схема.
        """
        # Хранилище значений: {register_name: {field: value}}
        self._data: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (registers or {}).items()}
        # Схема полей для get_fields()
        self._schema: dict[str, list[tuple[str, type]]] = dict(fields_schema or {})

    def get_fields(self, register_name: str) -> list[_FieldInfoLike]:
        """Вернуть список FieldInfoLike для register_name.

        Returns:
            Список _FieldInfoLike из _schema[register_name]. Пустой если нет регистра.
        """
        schema_fields = self._schema.get(register_name, [])
        return [_FieldInfoLike(fname, ftype) for fname, ftype in schema_fields]

    def get_register(self, register_name: str) -> "_FakeRegister | None":
        """Вернуть fake-регистр (object с атрибутами) или None."""
        if register_name not in self._data:
            return None
        return _FakeRegister(self._data[register_name])

    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> tuple[bool, str | None]:
        """Установить значение поля.

        Returns:
            (True, None) — при успехе.
            (False, str) — если регистр не найден или поле отсутствует.
        """
        if register_name not in self._data:
            return False, f"Регистр '{register_name}' не найден"
        reg_data = self._data[register_name]
        if field_name not in reg_data:
            return False, f"Поле '{field_name}' не найдено в регистре '{register_name}'"
        reg_data[field_name] = value
        return True, None


class _FakeRegister:
    """Объект-доступ к данным регистра через атрибуты (имитирует Pydantic instance)."""

    def __init__(self, data: dict[str, Any]) -> None:
        # Храним данные в __dict__ для hasattr/getattr совместимости
        for k, v in data.items():
            object.__setattr__(self, k, v)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)


# ==============================================================================
# Вспомогательные фабрики для fixture-данных
# ==============================================================================


def _make_topology_dict(
    process_name: str = "proc_a",
    plugins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Создать минимальный topology dict с одним процессом."""
    if plugins is None:
        plugins = [{"plugin_name": "blur_plugin"}]
    return {
        "processes": [
            {
                "process_name": process_name,
                "plugins": plugins,
            }
        ],
        "wires": [],
        "displays": [],
        "metadata": {},
    }


def _make_plugin_spec(name: str = "blur_plugin") -> PluginSpec:
    """Создать минимальный PluginSpec для тестов."""
    return PluginSpec(
        name=name,
        category="processing",
        description=f"Тестовый плагин {name}",
        config_schema={"register_classes": (name.title() + "Register",)},
    )


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def plugin_spec() -> PluginSpec:
    """PluginSpec для blur_plugin."""
    return _make_plugin_spec("blur_plugin")


@pytest.fixture
def catalog(plugin_spec: PluginSpec) -> _FakePluginCatalog:
    """Fake catalog с одним плагином blur_plugin."""
    return _FakePluginCatalog({"blur_plugin": plugin_spec})


@pytest.fixture
def topology_repo() -> _FakeTopologyRepository:
    """Fake topology repo: proc_a с одним плагином blur_plugin."""
    return _FakeTopologyRepository(
        _make_topology_dict(
            process_name="proc_a",
            plugins=[{"plugin_name": "blur_plugin"}],
        )
    )


@pytest.fixture
def registers_manager() -> _FakeRegistersManager:
    """Fake registers manager с полем 'kernel_size' у blur_plugin."""
    return _FakeRegistersManager(
        registers={"blur_plugin": {"kernel_size": 5, "sigma": 1.0}},
        fields_schema={"blur_plugin": [("kernel_size", int), ("sigma", float)]},
    )


@pytest.fixture
def adapter(
    registers_manager: _FakeRegistersManager,
    topology_repo: _FakeTopologyRepository,
    catalog: _FakePluginCatalog,
) -> RegistersBackendFromManager:
    """Adapter RegistersBackendFromManager с fake зависимостями."""
    return RegistersBackendFromManager(
        registers_manager=registers_manager,
        topology_repo=topology_repo,
        plugin_catalog=catalog,
    )


# ==============================================================================
# Тест 1: get_field_specs для известного плагина
# ==============================================================================


def test_get_field_specs_for_known_plugin(
    adapter: RegistersBackendFromManager,
) -> None:
    """get_field_specs('proc_a', 0) возвращает корректный tuple[FieldSpec, ...]."""
    specs = adapter.get_field_specs("proc_a", 0)

    assert isinstance(specs, tuple)
    assert len(specs) == 2  # kernel_size + sigma

    # Проверяем kernel_size
    kernel_spec = next((s for s in specs if s.name == "kernel_size"), None)
    assert kernel_spec is not None, "FieldSpec для kernel_size не найден"
    assert isinstance(kernel_spec, FieldSpec)
    assert kernel_spec.dtype == "int"

    # Проверяем sigma
    sigma_spec = next((s for s in specs if s.name == "sigma"), None)
    assert sigma_spec is not None, "FieldSpec для sigma не найден"
    assert sigma_spec.dtype == "float"


# ==============================================================================
# Тест 2: round-trip set/get value
# ==============================================================================


def test_get_value_set_value_roundtrip(
    adapter: RegistersBackendFromManager,
) -> None:
    """set_value + get_value возвращает то же значение."""
    # Начальное значение
    initial = adapter.get_value("proc_a", 0, "kernel_size")
    assert initial == 5

    # Установить новое значение
    adapter.set_value("proc_a", 0, "kernel_size", 11)

    # Прочитать — должно вернуться 11
    updated = adapter.get_value("proc_a", 0, "kernel_size")
    assert updated == 11


# ==============================================================================
# Тест 3: unknown process → DomainError
# ==============================================================================


def test_unknown_process_raises_domain_error(
    adapter: RegistersBackendFromManager,
) -> None:
    """DomainError при обращении к несуществующему process_name."""
    with pytest.raises(DomainError, match="proc_unknown"):
        adapter.get_field_specs("proc_unknown", 0)


# ==============================================================================
# Тест 4: plugin_index out of range → DomainError
# ==============================================================================


def test_plugin_index_out_of_range_raises_domain_error(
    adapter: RegistersBackendFromManager,
) -> None:
    """DomainError при plugin_index >= len(process.plugins)."""
    with pytest.raises(DomainError, match="plugin_index"):
        adapter.get_field_specs("proc_a", 99)


@pytest.mark.parametrize("bad_index", [-1, -100])
def test_negative_plugin_index_raises_domain_error(
    adapter: RegistersBackendFromManager,
    bad_index: int,
) -> None:
    """DomainError при отрицательном plugin_index."""
    with pytest.raises(DomainError, match="plugin_index"):
        adapter.get_field_specs("proc_a", bad_index)


# ==============================================================================
# Тест 5: unknown plugin_name в catalog → DomainError
# ==============================================================================


def test_unknown_plugin_name_in_catalog_raises_domain_error(
    registers_manager: _FakeRegistersManager,
    topology_repo: _FakeTopologyRepository,
) -> None:
    """DomainError если plugin_name из topology не найден в PluginCatalog."""
    # Catalog пустой — blur_plugin там нет
    empty_catalog = _FakePluginCatalog({})
    adapter = RegistersBackendFromManager(
        registers_manager=registers_manager,
        topology_repo=topology_repo,
        plugin_catalog=empty_catalog,
    )

    with pytest.raises(DomainError, match="blur_plugin"):
        adapter.get_field_specs("proc_a", 0)


# ==============================================================================
# Тест 6: плагин без регистров → пустой tuple для get_field_specs
# ==============================================================================


def test_plugin_without_registers_returns_empty_tuple(
    topology_repo: _FakeTopologyRepository,
    catalog: _FakePluginCatalog,
) -> None:
    """Если RegistersManager не содержит регистра для плагина — get_field_specs() → ()."""
    # RegistersManager без данных для blur_plugin
    empty_rm = _FakeRegistersManager(
        registers={},  # нет данных
        fields_schema={},  # нет схемы
    )
    adapter = RegistersBackendFromManager(
        registers_manager=empty_rm,
        topology_repo=topology_repo,
        plugin_catalog=catalog,
    )

    specs = adapter.get_field_specs("proc_a", 0)
    assert specs == ()


# ==============================================================================
# Тест 7: Protocol-совместимость (assignment check)
# ==============================================================================


def test_satisfies_protocol(
    adapter: RegistersBackendFromManager,
) -> None:
    """RegistersBackendFromManager удовлетворяет Protocol RegistersBackend."""
    # Структурная проверка: assignment к Protocol-типизированной переменной
    typed_backend: RegistersBackend = adapter  # type: ignore[assignment]

    # Проверяем наличие всех методов Protocol
    assert callable(typed_backend.get_field_specs)
    assert callable(typed_backend.get_value)
    assert callable(typed_backend.set_value)

    # Функциональная проверка через Protocol
    specs = typed_backend.get_field_specs("proc_a", 0)
    assert isinstance(specs, tuple)


# ==============================================================================
# Тест 8: get_value → DomainError если регистр не найден в RegistersManager
# ==============================================================================


def test_get_value_raises_domain_error_when_register_missing(
    topology_repo: _FakeTopologyRepository,
    catalog: _FakePluginCatalog,
) -> None:
    """DomainError если catalog знает плагин, но RegistersManager не имеет регистра."""
    empty_rm = _FakeRegistersManager(registers={}, fields_schema={})
    adapter = RegistersBackendFromManager(
        registers_manager=empty_rm,
        topology_repo=topology_repo,
        plugin_catalog=catalog,
    )

    with pytest.raises(DomainError, match="blur_plugin"):
        adapter.get_value("proc_a", 0, "kernel_size")


# ==============================================================================
# Тест 9: get_value → KeyError если поле не существует
# ==============================================================================


def test_get_value_raises_key_error_for_unknown_field(
    adapter: RegistersBackendFromManager,
) -> None:
    """KeyError при обращении к несуществующему полю регистра."""
    with pytest.raises(KeyError, match="nonexistent_field"):
        adapter.get_value("proc_a", 0, "nonexistent_field")


# ==============================================================================
# Тест 10: set_value → DomainError при ошибке RegistersManager
# ==============================================================================


def test_set_value_raises_domain_error_on_rm_failure(
    topology_repo: _FakeTopologyRepository,
    catalog: _FakePluginCatalog,
) -> None:
    """DomainError если RegistersManager.set_field_value() вернул (False, msg)."""
    # RegistersManager знает регистр, но не поле nonexistent_field
    rm = _FakeRegistersManager(
        registers={"blur_plugin": {"kernel_size": 5}},
        fields_schema={"blur_plugin": [("kernel_size", int)]},
    )
    adapter = RegistersBackendFromManager(
        registers_manager=rm,
        topology_repo=topology_repo,
        plugin_catalog=catalog,
    )

    # Попытка установить несуществующее поле
    with pytest.raises(DomainError):
        adapter.set_value("proc_a", 0, "nonexistent_field", 42)


# ==============================================================================
# Тест 11: несколько плагинов — правильный выбор по индексу
# ==============================================================================


def test_multiple_plugins_correct_index_resolution() -> None:
    """Adapter правильно разрешает plugin_index=1 (второй плагин) среди нескольких."""
    # Два плагина в процессе
    topology_repo = _FakeTopologyRepository(
        _make_topology_dict(
            process_name="proc_multi",
            plugins=[
                {"plugin_name": "blur_plugin"},
                {"plugin_name": "threshold_plugin"},
            ],
        )
    )
    # Catalog знает оба плагина
    catalog = _FakePluginCatalog(
        {
            "blur_plugin": _make_plugin_spec("blur_plugin"),
            "threshold_plugin": _make_plugin_spec("threshold_plugin"),
        }
    )
    # RegistersManager с данными для обоих
    rm = _FakeRegistersManager(
        registers={
            "blur_plugin": {"kernel_size": 5},
            "threshold_plugin": {"threshold": 128},
        },
        fields_schema={
            "blur_plugin": [("kernel_size", int)],
            "threshold_plugin": [("threshold", int)],
        },
    )
    adapter = RegistersBackendFromManager(
        registers_manager=rm,
        topology_repo=topology_repo,
        plugin_catalog=catalog,
    )

    # plugin_index=0 → blur_plugin
    specs_0 = adapter.get_field_specs("proc_multi", 0)
    assert len(specs_0) == 1
    assert specs_0[0].name == "kernel_size"

    # plugin_index=1 → threshold_plugin
    specs_1 = adapter.get_field_specs("proc_multi", 1)
    assert len(specs_1) == 1
    assert specs_1[0].name == "threshold"

    # get_value для второго плагина
    val = adapter.get_value("proc_multi", 1, "threshold")
    assert val == 128
