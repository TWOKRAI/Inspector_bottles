"""Тесты Task 7.3 — RegistersManagerV2.

Проверяем:
1. from_registry() — автобилд из PluginRegistry
2. from_topology() — автобилд из topology dict с YAML overrides
3. get_fields() — FieldInfo с метаданными
4. get_categories() — группировка по категориям
5. set_value / validate — делегирование в FW
6. Обратная совместимость с FW RegistersManager API
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.data_schema_module.core.field_meta import FieldMeta
from multiprocess_framework.modules.data_schema_module.core.schema_base import SchemaBase
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.registry import PluginEntry

from multiprocess_prototype.registers.field_info import FieldInfo, extract_fields
from multiprocess_prototype.registers.manager import RegistersManagerV2


# --- Фикстуры ---


class _TestRegA(SchemaBase):
    """Register A — с FieldMeta."""
    threshold: Annotated[int, FieldMeta("Порог", min=0, max=100, unit="%")] = 50
    enabled: Annotated[bool, FieldMeta("Включён")] = True


class _TestRegB(SchemaBase):
    """Register B — для второго плагина."""
    gain: Annotated[float, FieldMeta("Усиление", min=0.0, max=10.0)] = 1.0
    mode: Annotated[str, FieldMeta("Режим")] = "auto"


class _MockRegistry:
    """Мок PluginRegistry."""

    def __init__(self, entries: list[PluginEntry]) -> None:
        self._entries = entries
        self._by_name = {e.name: e for e in entries}

    def list(self) -> list[PluginEntry]:
        return self._entries

    def get(self, name: str) -> PluginEntry | None:
        return self._by_name.get(name)


def _make_entry(name: str, category: str, reg_classes: list) -> PluginEntry:
    """Создать PluginEntry с register_classes без реального plugin class."""
    entry = MagicMock(spec=PluginEntry)
    entry.name = name
    entry.category = category
    entry.register_classes = reg_classes
    return entry


@pytest.fixture
def registry_with_plugins() -> _MockRegistry:
    """Registry с двумя плагинами."""
    return _MockRegistry([
        _make_entry("plugin_a", "processing", [_TestRegA]),
        _make_entry("plugin_b", "source", [_TestRegB]),
        _make_entry("plugin_c", "lifecycle", []),  # без register
    ])


@pytest.fixture
def topology_dict() -> dict:
    """Topology dict с двумя процессами."""
    return {
        "processes": [
            {
                "process_name": "proc_0",
                "plugins": [
                    {"plugin_name": "plugin_a", "threshold": 75},
                ],
            },
            {
                "process_name": "proc_1",
                "plugins": [
                    {"plugin_name": "plugin_b", "gain": 2.5, "mode": "manual"},
                ],
            },
        ]
    }


# --- Тесты: from_registry ---


class TestFromRegistry:
    """RegistersManagerV2.from_registry()."""

    def test_builds_from_registry(self, registry_with_plugins):
        """Строит менеджер из PluginRegistry."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        names = mgr.register_names()
        assert "plugin_a" in names
        assert "plugin_b" in names
        assert "plugin_c" not in names  # нет register_classes

    def test_registers_have_defaults(self, registry_with_plugins):
        """Регистры создаются с defaults."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        reg_a = mgr.get_register("plugin_a")
        assert reg_a.threshold == 50
        assert reg_a.enabled is True

    def test_categories_populated(self, registry_with_plugins):
        """Категории заполнены."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        cats = mgr.get_categories()
        assert "processing" in cats
        assert "plugin_a" in cats["processing"]
        assert "source" in cats
        assert "plugin_b" in cats["source"]


# --- Тесты: from_topology ---


class TestFromTopology:
    """RegistersManagerV2.from_topology()."""

    def test_builds_with_yaml_overrides(self, topology_dict, registry_with_plugins):
        """Строит менеджер с YAML overrides."""
        mgr = RegistersManagerV2.from_topology(
            topology_dict, plugin_registry=registry_with_plugins,
        )
        reg_a = mgr.get_register("plugin_a")
        assert reg_a is not None
        assert reg_a.threshold == 75  # override из topology

    def test_multiple_processes(self, topology_dict, registry_with_plugins):
        """Плагины из разных процессов."""
        mgr = RegistersManagerV2.from_topology(
            topology_dict, plugin_registry=registry_with_plugins,
        )
        reg_b = mgr.get_register("plugin_b")
        assert reg_b.gain == 2.5
        assert reg_b.mode == "manual"


# --- Тесты: get_fields ---


class TestGetFields:
    """get_fields() → list[FieldInfo]."""

    def test_fields_extracted(self, registry_with_plugins):
        """Поля извлекаются с метаданными."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        fields = mgr.get_fields("plugin_a")
        assert len(fields) == 2  # threshold + enabled
        names = {f.field_name for f in fields}
        assert names == {"threshold", "enabled"}

    def test_field_has_meta(self, registry_with_plugins):
        """FieldInfo содержит FieldMeta."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        fields = mgr.get_fields("plugin_a")
        threshold_field = next(f for f in fields if f.field_name == "threshold")
        assert threshold_field.meta is not None
        assert threshold_field.min_value == 0
        assert threshold_field.max_value == 100
        assert threshold_field.unit == "%"

    def test_field_title(self, registry_with_plugins):
        """FieldInfo.title из FieldMeta.description."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        fields = mgr.get_fields("plugin_a")
        threshold_field = next(f for f in fields if f.field_name == "threshold")
        assert threshold_field.title == "Порог"

    def test_unknown_plugin_returns_empty(self, registry_with_plugins):
        """Несуществующий плагин → пустой список."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        assert mgr.get_fields("nonexistent") == []

    def test_fields_cached(self, registry_with_plugins):
        """Повторный вызов — из кэша."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        fields1 = mgr.get_fields("plugin_a")
        fields2 = mgr.get_fields("plugin_a")
        assert fields1 is fields2


# --- Тесты: set_value / validate ---


class TestSetValueValidate:
    """set_value / validate — делегирование в FW."""

    def test_set_value_ok(self, registry_with_plugins):
        """set_value обновляет значение."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        ok = mgr.set_value("plugin_a", "threshold", 75)
        assert ok is True
        assert mgr.get_register("plugin_a").threshold == 75

    def test_set_value_invalid(self, registry_with_plugins):
        """set_value с невалидным значением → False."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        ok = mgr.set_value("plugin_a", "threshold", 999)
        assert ok is False

    def test_validate_ok(self, registry_with_plugins):
        """validate проходит для корректного значения."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        ok, err = mgr.validate("plugin_a", "threshold", 50)
        assert ok is True
        assert err is None

    def test_validate_fail(self, registry_with_plugins):
        """validate не проходит для невалидного значения."""
        mgr = RegistersManagerV2.from_registry(registry_with_plugins)
        ok, err = mgr.validate("plugin_a", "threshold", -10)
        assert ok is False
        assert err is not None


# --- Тесты: extract_fields ---


class TestExtractFields:
    """extract_fields() утилита."""

    def test_extract_all_fields(self):
        """Извлекает все поля."""
        fields = extract_fields("test", _TestRegA, category="processing")
        assert len(fields) == 2

    def test_field_default(self):
        """default корректен."""
        fields = extract_fields("test", _TestRegA)
        threshold = next(f for f in fields if f.field_name == "threshold")
        assert threshold.default == 50
