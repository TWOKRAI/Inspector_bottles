# -*- coding: utf-8 -*-
"""Тесты TreeNavTabPresenter — pure-Python (без Qt).

Цель: проверить универсальную навигацию (реестр секций, ленивые узлы,
переключение content/action stack, on_activated / on_deactivated) на
фейковом view, не требующем PySide6.

См. ADR-126.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Optional

import pytest

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    SectionProtocol,
    TreeNavTabPresenter,
)


# ---------------------------------------------------------------------------
# Pure-Python: модуль не тянет PySide6
# ---------------------------------------------------------------------------


def test_tree_nav_presenter_module_imports_without_qt() -> None:
    mod = importlib.import_module("multiprocess_framework.modules.frontend_module.widgets.tabs.tree_nav_presenter")
    assert "QWidget" not in vars(mod)
    assert "QStackedWidget" not in vars(mod)


def test_tabs_facade_exports_tree_nav_presenter() -> None:
    pkg = importlib.import_module("multiprocess_framework.modules.frontend_module.widgets.tabs")
    assert "TreeNavTabPresenter" in pkg.__all__
    assert hasattr(pkg, "TreeNavTabPresenter")


# ---------------------------------------------------------------------------
# Фейковый view: записывает все вызовы, не требует Qt
# ---------------------------------------------------------------------------


@dataclass
class _FakeView:
    content_index: int = -1
    action_index: int = -1
    selected_tree_key: Optional[str] = None
    created_lazy_keys: list[str] = field(default_factory=list)

    def set_content_index(self, index: int) -> None:
        self.content_index = index

    def set_action_index(self, index: int) -> None:
        self.action_index = index

    def select_tree_key(self, key: str) -> None:
        self.selected_tree_key = key

    def create_lazy_section(self, key: str) -> None:
        """Фейковая фабрика: имитирует tab.py — регистрирует индексы у presenter."""
        self.created_lazy_keys.append(key)


@dataclass
class _FakeSection:
    """Pure-Python заглушка SectionProtocol — учитывает вызовы on_activated / on_deactivated."""

    key: str
    title: str = "Section"
    activated_count: int = 0
    deactivated_count: int = 0

    def widget(self) -> "_FakeSection":
        return self

    def action_buttons(self) -> list:
        return []

    def on_activated(self) -> None:
        self.activated_count += 1

    def on_deactivated(self) -> None:
        self.deactivated_count += 1


@pytest.fixture
def view() -> _FakeView:
    return _FakeView()


@pytest.fixture
def presenter(view: _FakeView) -> TreeNavTabPresenter:
    return TreeNavTabPresenter(view=view, rm=None, ui=None)


# ---------------------------------------------------------------------------
# Реестр секций и индексов
# ---------------------------------------------------------------------------


def test_register_section_stores_in_registry(presenter: TreeNavTabPresenter) -> None:
    section = _FakeSection("system_settings", "Настройки системы")
    presenter.register_section(section)
    assert presenter.section("system_settings") is section


def test_section_returns_none_for_unknown_key(presenter: TreeNavTabPresenter) -> None:
    assert presenter.section("nope") is None


def test_register_content_and_action_pages(presenter: TreeNavTabPresenter) -> None:
    presenter.register_content_page("a", 3)
    presenter.register_action_page("a", 7)
    presenter.register_action_page("_empty", 0)
    assert presenter.get_action_index("a") == 7
    assert presenter.get_action_index("unknown") == 0  # fallback to _empty


# ---------------------------------------------------------------------------
# Навигация
# ---------------------------------------------------------------------------


def test_on_tree_item_changed_switches_content_and_action(presenter: TreeNavTabPresenter, view: _FakeView) -> None:
    presenter.register_content_page("history", 4)
    presenter.register_action_page("history", 2)
    presenter.register_action_page("_empty", 0)

    presenter.on_tree_item_changed("history")

    assert view.content_index == 4
    assert view.action_index == 2
    assert presenter.current_key == "history"


def test_on_tree_item_changed_calls_section_lifecycle(presenter: TreeNavTabPresenter, view: _FakeView) -> None:
    a = _FakeSection("a")
    b = _FakeSection("b")
    presenter.register_section(a)
    presenter.register_section(b)
    presenter.register_content_page("a", 0)
    presenter.register_content_page("b", 1)
    presenter.register_action_page("_empty", 9)

    presenter.on_tree_item_changed("a")
    assert a.activated_count == 1 and a.deactivated_count == 0

    presenter.on_tree_item_changed("b")
    assert a.deactivated_count == 1
    assert b.activated_count == 1


def test_on_tree_item_changed_ignores_empty_key(presenter: TreeNavTabPresenter, view: _FakeView) -> None:
    presenter.on_tree_item_changed("")
    assert presenter.current_key is None
    assert view.content_index == -1


def test_on_tree_item_changed_uses_empty_action_when_no_mapping(
    presenter: TreeNavTabPresenter, view: _FakeView
) -> None:
    presenter.register_content_page("k", 5)
    presenter.register_action_page("_empty", 0)
    presenter.on_tree_item_changed("k")
    assert view.action_index == 0


def test_navigate_to_delegates_to_view_select_tree_key(presenter: TreeNavTabPresenter, view: _FakeView) -> None:
    presenter.navigate_to("appearance")
    assert view.selected_tree_key == "appearance"


def test_lifecycle_exception_doesnt_break_navigation(presenter: TreeNavTabPresenter, view: _FakeView) -> None:
    class _BrokenSection(_FakeSection):
        def on_activated(self) -> None:
            raise RuntimeError("boom")

    sec = _BrokenSection("broken")
    presenter.register_section(sec)
    presenter.register_content_page("broken", 0)
    presenter.register_action_page("_empty", 0)
    # не должно поднимать исключение
    presenter.on_tree_item_changed("broken")
    assert presenter.current_key == "broken"


# ---------------------------------------------------------------------------
# Ленивые секции
# ---------------------------------------------------------------------------


def test_register_lazy_section_marks_pending(presenter: TreeNavTabPresenter) -> None:
    presenter.register_lazy_section("users")
    assert presenter.is_lazy_section("users") is True


def test_lazy_section_no_longer_pending_after_page_registered(
    presenter: TreeNavTabPresenter,
) -> None:
    presenter.register_lazy_section("users")
    presenter.register_content_page("users", 10)
    assert presenter.is_lazy_section("users") is False


def test_ensure_lazy_section_calls_view_factory(presenter: TreeNavTabPresenter, view: _FakeView) -> None:
    presenter.register_lazy_section("users")
    presenter.ensure_lazy_section("users")
    assert view.created_lazy_keys == ["users"]


def test_ensure_lazy_section_skips_non_lazy(presenter: TreeNavTabPresenter, view: _FakeView) -> None:
    presenter.ensure_lazy_section("not_registered")
    assert view.created_lazy_keys == []


def test_notify_lazy_section_created_registers_indices(
    presenter: TreeNavTabPresenter,
) -> None:
    presenter.register_lazy_section("users")
    sentinel = object()
    presenter.notify_lazy_section_created("users", sentinel, action_idx=2, content_idx=5)
    assert presenter.is_lazy_section("users") is False
    assert presenter.get_action_index("users") == 2


def test_on_tree_item_changed_triggers_lazy_creation(presenter: TreeNavTabPresenter, view: _FakeView) -> None:
    """При переключении на ленивый узел presenter сначала просит view создать виджет."""
    presenter.register_lazy_section("users")
    presenter.register_action_page("_empty", 0)

    presenter.on_tree_item_changed("users")
    assert view.created_lazy_keys == ["users"]


# ---------------------------------------------------------------------------
# Совместимость с SectionProtocol
# ---------------------------------------------------------------------------


def test_fake_section_satisfies_section_protocol() -> None:
    """Фейковая секция теста удовлетворяет реальному SectionProtocol — без Qt."""
    sec = _FakeSection("k")
    assert isinstance(sec, SectionProtocol)
