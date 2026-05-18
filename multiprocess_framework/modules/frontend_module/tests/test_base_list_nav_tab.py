# -*- coding: utf-8 -*-
"""Тесты BaseListNavTab --- динамический CRUD-список.

Проверяют: CRUD-операции (add/remove/rename/select), сигналы,
переключение content_stack, изоляцию от SectionSpec/TreeNavTabPresenter.

См. Phase 6c (plans/tab-template-extraction/plan.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    BaseListNavTab,
)
from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_layouts import (
    StandardTabLayout,
)


# ---------------------------------------------------------------------------
# Фейковый layout (QWidget с TabLayoutProtocol-методами)
# ---------------------------------------------------------------------------


class _MockLayoutWrapper(QWidget):
    """Обёртка: QWidget, делегирующий TabLayoutProtocol в mock."""

    def __init__(self, mock: MagicMock) -> None:
        super().__init__()
        self._mock = mock

    def set_title(self, text: str) -> None:
        self._mock.set_title(text)

    def set_action_widget(self, widget: QWidget) -> None:
        self._mock.set_action_widget(widget)

    def set_nav_widget(self, widget: QWidget) -> None:
        self._mock.set_nav_widget(widget)

    def set_content_widget(self, widget: QWidget) -> None:
        self._mock.set_content_widget(widget)

    def enable_undo_redo(self, action_bus: object | None) -> None:
        self._mock.enable_undo_redo(action_bus)

    def register_inner_scrolls(self, widget: QWidget) -> None:
        self._mock.register_inner_scrolls(widget)

    def connect_stack(self, stack: QWidget, role: str) -> None:
        self._mock.connect_stack(stack, role)

    def refresh_after_page_change(self, role: str) -> None:
        self._mock.refresh_after_page_change(role)


# ---------------------------------------------------------------------------
# Конкретная реализация BaseListNavTab для тестов
# ---------------------------------------------------------------------------


class _ConcreteListNavTab(BaseListNavTab):
    """Тестовый подкласс с простым content-виджетом."""

    def _create_item_widget(self, key: str) -> QWidget:
        return QLabel(f"Content: {key}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_layout() -> tuple[MagicMock, type]:
    mock = MagicMock()
    wrapper = _MockLayoutWrapper(mock)

    def factory() -> _MockLayoutWrapper:
        return wrapper

    return mock, factory


@pytest.fixture
def tab(qtbot, mock_layout):
    """Готовый экземпляр _ConcreteListNavTab."""
    _, factory = mock_layout
    t = _ConcreteListNavTab(
        title="Test List Tab",
        ctx=None,
        layout_factory=factory,
    )
    qtbot.addWidget(t)
    return t


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestBaseListNavTab:
    """CRUD-контракт и сигналы BaseListNavTab."""

    def test_concrete_list_nav_tab_basic(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """Конкретный подкласс создаётся с layout_factory=StandardTabLayout."""
        tab = _ConcreteListNavTab(
            title="Standard Test",
            ctx=None,
            layout_factory=lambda: StandardTabLayout(show_sub_nav=False),
        )
        qtbot.addWidget(tab)
        assert isinstance(tab, BaseListNavTab)
        assert isinstance(tab, QWidget)
        assert tab.nav_widget is not None

    def test_add_item_appends_to_nav(self, tab) -> None:
        """add_item('a', 'Recipe A') добавляет элемент в nav."""
        tab.add_item("a", "Recipe A")
        assert tab.nav_widget.count() == 1
        item = tab.nav_widget.item(0)
        assert item.text() == "Recipe A"
        assert item.data(Qt.ItemDataRole.UserRole) == "a"

    def test_add_item_registers_content_widget(self, tab) -> None:
        """add_item регистрирует content widget в стеке."""
        tab.add_item("a", "Recipe A")
        assert tab._content_stack.count() == 1
        assert "a" in tab._key_to_index

    def test_select_item_switches_stack(self, tab) -> None:
        """select_item('b') переключает content_stack на 'b'."""
        tab.add_item("a", "A")
        tab.add_item("b", "B")
        tab.select_item("b")
        assert tab._content_stack.currentIndex() == tab._key_to_index["b"]

    def test_remove_item_drops_from_nav_and_stack(self, tab) -> None:
        """remove_item удаляет из nav и stack."""
        tab.add_item("a", "A")
        tab.add_item("b", "B")
        assert tab.nav_widget.count() == 2
        assert tab._content_stack.count() == 2

        tab.remove_item("a")
        assert tab.nav_widget.count() == 1
        assert tab._content_stack.count() == 1
        assert "a" not in tab._key_to_index
        assert "b" in tab._key_to_index

    def test_rename_item_updates_label(self, tab) -> None:
        """rename_item обновляет label QListWidgetItem."""
        tab.add_item("a", "Old Name")
        tab.rename_item("a", "New Name")
        assert tab.nav_widget.item(0).text() == "New Name"

    def test_item_selected_signal_emits_on_nav_change(self, qtbot, tab) -> None:
        """Клик в QListWidget эмитит item_selected."""
        tab.add_item("a", "A")
        tab.add_item("b", "B")
        # Сначала выбрать a, чтобы потом переключение на b сработало
        tab.nav_widget.setCurrentRow(0)

        with qtbot.waitSignal(tab.item_selected, timeout=1000) as blocker:
            tab.nav_widget.setCurrentRow(1)

        assert blocker.args == ["b"]

    def test_base_list_nav_tab_no_section_spec(self) -> None:
        """Модуль не импортирует SectionSpec/SectionProtocol/TreeNavTabPresenter."""
        import multiprocess_framework.modules.frontend_module.widgets.tabs.base_list_nav_tab as mod

        source_names = dir(mod)
        forbidden = {"SectionSpec", "SectionProtocol", "TreeNavTabPresenter"}
        found = forbidden & set(source_names)
        assert found == set(), f"Найдены запрещённые имена: {found}"
