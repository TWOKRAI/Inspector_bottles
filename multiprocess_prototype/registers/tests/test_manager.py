"""Тесты build_rm_from_topology — prototype-specific функция.

Тесты from_registry, get_fields, get_categories, set_value, validate
перенесены в multiprocess_framework/modules/registers_module/tests/test_manager.py.
"""

from __future__ import annotations

from typing import Annotated
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase
from multiprocess_framework.modules.process_module.plugins.registry import PluginEntry

from multiprocess_prototype.registers.manager import build_rm_from_topology


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
    return _MockRegistry(
        [
            _make_entry("plugin_a", "processing", [_TestRegA]),
            _make_entry("plugin_b", "source", [_TestRegB]),
            _make_entry("plugin_c", "lifecycle", []),  # без register
        ]
    )


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


# --- Тесты: build_rm_from_topology ---


class TestBuildRmFromTopology:
    """build_rm_from_topology() — prototype-specific функция."""

    def test_builds_with_yaml_overrides(self, topology_dict, registry_with_plugins):
        """Строит менеджер с YAML overrides."""
        mgr = build_rm_from_topology(
            topology_dict,
            plugin_registry=registry_with_plugins,
        )
        reg_a = mgr.get_register("plugin_a")
        assert reg_a is not None
        assert reg_a.threshold == 75  # override из topology

    def test_multiple_processes(self, topology_dict, registry_with_plugins):
        """Плагины из разных процессов."""
        mgr = build_rm_from_topology(
            topology_dict,
            plugin_registry=registry_with_plugins,
        )
        reg_b = mgr.get_register("plugin_b")
        assert reg_b.gain == 2.5
        assert reg_b.mode == "manual"

    def test_empty_topology(self):
        """Пустая topology → пустой менеджер."""
        mgr = build_rm_from_topology({})
        assert mgr.register_names() == []

    def test_no_registry(self, topology_dict):
        """Без registry → пустой менеджер (плагины не резолвятся)."""
        mgr = build_rm_from_topology(topology_dict, plugin_registry=None)
        assert mgr.register_names() == []
