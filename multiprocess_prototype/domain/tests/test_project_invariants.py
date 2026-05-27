# -*- coding: utf-8 -*-
"""
test_project_invariants.py -- тесты на 5 invariants Project aggregate (Task B.4).

Тестирует:
  - _check_unique_process_names
  - _check_no_dangling_wires
  - _check_no_cycles
  - _check_plugin_references
  - _check_display_references

In-memory fakes (не MagicMock) для Protocols.
"""

from __future__ import annotations

import pytest

from multiprocess_prototype.domain.entities import (
    DisplayInstance,
    PluginInstance,
    Process,
    Topology,
    Wire,
)
from multiprocess_prototype.domain.entities.project import (
    ApplyContext,
    _check_display_references,
    _check_no_cycles,
    _check_no_dangling_wires,
    _check_plugin_references,
    _check_unique_process_names,
)
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.protocols import (
    DisplaySpec,
    PluginSpec,
)


# ======================================================================
# In-memory fakes для Protocols
# ======================================================================


class _FakePluginCatalog:
    """In-memory реализация PluginCatalog для тестов."""

    def __init__(self, known: set[str]) -> None:
        self._known = known

    def list_plugins(self) -> tuple[PluginSpec, ...]:
        return tuple(PluginSpec(name=n, category="cat") for n in self._known)

    def resolve(self, plugin_name: str) -> PluginSpec | None:
        if plugin_name in self._known:
            return PluginSpec(name=plugin_name, category="cat")
        return None

    def categories(self) -> tuple[str, ...]:
        return ("cat",)


class _FakeDisplayCatalog:
    """In-memory реализация DisplayCatalog для тестов."""

    def __init__(self, known: set[str]) -> None:
        self._known = known

    def list_displays(self) -> tuple[DisplaySpec, ...]:
        return tuple(DisplaySpec(display_id=d, display_name=d) for d in self._known)

    def resolve(self, display_id: str) -> DisplaySpec | None:
        if display_id in self._known:
            return DisplaySpec(display_id=display_id, display_name=display_id)
        return None


# ======================================================================
# test_unique_process_names
# ======================================================================


def test_unique_names_ok() -> None:
    """Топология с уникальными именами проходит проверку."""
    topo = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
            Process(process_name="c"),
        )
    )
    # Не должно бросить исключение
    _check_unique_process_names(topo)


def test_unique_names_duplicate_raises() -> None:
    """Топология с дублирующимся именем поднимает DomainError."""
    topo = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
            Process(process_name="a"),
        )
    )
    with pytest.raises(DomainError, match="process_name 'a' already exists"):
        _check_unique_process_names(topo)


# ======================================================================
# test_no_dangling_wires
# ======================================================================


def test_no_dangling_wires_ok() -> None:
    """Все wire-ы ссылаются на существующие процессы."""
    topo = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
        ),
        wires=(
            Wire(source="a", target="b"),
            Wire(source="a.plugin1", target="b.plugin2"),
        ),
    )
    _check_no_dangling_wires(topo)


def test_dangling_source_raises() -> None:
    """Wire с source, ссылающимся на несуществующий процесс, вызывает DomainError."""
    topo = Topology(
        processes=(Process(process_name="a"),),
        wires=(Wire(source="missing", target="a"),),
    )
    with pytest.raises(DomainError, match="dangling wire source.*missing"):
        _check_no_dangling_wires(topo)


def test_dangling_target_raises() -> None:
    """Wire с target, ссылающимся на несуществующий процесс, вызывает DomainError."""
    topo = Topology(
        processes=(Process(process_name="a"),),
        wires=(Wire(source="a", target="missing"),),
    )
    with pytest.raises(DomainError, match="dangling wire target.*missing"):
        _check_no_dangling_wires(topo)


# ======================================================================
# test_no_cycles
# ======================================================================


def test_no_cycles_simple() -> None:
    """Линейная цепочка A -> B -> C не содержит циклов."""
    topo = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
            Process(process_name="c"),
        ),
        wires=(
            Wire(source="a", target="b"),
            Wire(source="b", target="c"),
        ),
    )
    _check_no_cycles(topo)


def test_self_loop_raises() -> None:
    """Провод из процесса в самого себя -- цикл."""
    topo = Topology(
        processes=(Process(process_name="a"),),
        wires=(Wire(source="a", target="a"),),
    )
    with pytest.raises(DomainError, match="cycle detected"):
        _check_no_cycles(topo)


def test_3_node_cycle_raises() -> None:
    """Цикл A -> B -> C -> A обнаруживается."""
    topo = Topology(
        processes=(
            Process(process_name="a"),
            Process(process_name="b"),
            Process(process_name="c"),
        ),
        wires=(
            Wire(source="a", target="b"),
            Wire(source="b", target="c"),
            Wire(source="c", target="a"),
        ),
    )
    with pytest.raises(DomainError, match="cycle detected"):
        _check_no_cycles(topo)


# ======================================================================
# test_plugin_references
# ======================================================================


def test_plugin_references_ok() -> None:
    """Все plugin_name существуют в каталоге."""
    topo = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(
                    PluginInstance(plugin_name="blur"),
                    PluginInstance(plugin_name="resize"),
                ),
            ),
        ),
    )
    catalogs = ApplyContext(plugins=_FakePluginCatalog({"blur", "resize"}))
    _check_plugin_references(topo, catalogs)


def test_unknown_plugin_raises() -> None:
    """Неизвестный plugin_name вызывает DomainError."""
    topo = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(PluginInstance(plugin_name="unknown_plugin"),),
            ),
        ),
    )
    catalogs = ApplyContext(plugins=_FakePluginCatalog({"blur"}))
    with pytest.raises(DomainError, match="plugin 'unknown_plugin' not found"):
        _check_plugin_references(topo, catalogs)


def test_no_catalog_skipped() -> None:
    """Если catalogs.plugins is None, invariant пропускается без ошибки."""
    topo = Topology(
        processes=(
            Process(
                process_name="proc1",
                plugins=(PluginInstance(plugin_name="anything"),),
            ),
        ),
    )
    catalogs = ApplyContext(plugins=None)
    # Не должно бросить исключение
    _check_plugin_references(topo, catalogs)


# ======================================================================
# test_display_references
# ======================================================================


def test_display_references_ok() -> None:
    """Все display_id существуют в каталоге."""
    topo = Topology(
        processes=(Process(process_name="proc1"),),
        displays=(DisplayInstance(node_id="proc1.blur", display_id="main"),),
    )
    catalogs = ApplyContext(displays=_FakeDisplayCatalog({"main"}))
    _check_display_references(topo, catalogs)


def test_unknown_display_raises() -> None:
    """Неизвестный display_id вызывает DomainError."""
    topo = Topology(
        processes=(Process(process_name="proc1"),),
        displays=(DisplayInstance(node_id="proc1.blur", display_id="nonexistent"),),
    )
    catalogs = ApplyContext(displays=_FakeDisplayCatalog({"main"}))
    with pytest.raises(DomainError, match="display 'nonexistent' not found"):
        _check_display_references(topo, catalogs)
