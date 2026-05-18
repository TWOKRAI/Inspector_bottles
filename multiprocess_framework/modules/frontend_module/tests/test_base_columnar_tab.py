# -*- coding: utf-8 -*-
"""Тесты BaseColumnarTab --- nav-агностичная база для колоночных вкладок.

Проверяют: создание с конкретным подклассом, регистрацию content-виджетов,
переключение через select_key, изоляцию от SectionSpec/TreeNavTabPresenter.

См. Phase 6b (plans/tab-template-extraction/plan.md).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QLabel, QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    BaseColumnarTab,
)
from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_layouts import (
    DiffScrollTabLayout,
)


# ---------------------------------------------------------------------------
# Фейковый layout (QWidget с TabLayoutProtocol-методами)
# ---------------------------------------------------------------------------


class _MockLayoutWrapper(QWidget):
    """Обёртка: QWidget, который делегирует вызовы TabLayoutProtocol в mock."""

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
# Конкретная реализация для тестов
# ---------------------------------------------------------------------------


class _ConcreteColumnarTab(BaseColumnarTab):
    """Минимальная конкретная реализация BaseColumnarTab для тестов."""

    def __init__(self, **kwargs: Any) -> None:
        self.nav_changed_calls: list[str] = []
        super().__init__(**kwargs)

    def _build_nav_widget(self) -> QWidget:
        return QLabel("nav")

    def _on_nav_changed(self, key: str) -> None:
        self.nav_changed_calls.append(key)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_layout() -> tuple[MagicMock, type]:
    """Мок-layout и фабрика."""
    mock = MagicMock()
    wrapper = _MockLayoutWrapper(mock)

    def factory() -> _MockLayoutWrapper:
        return wrapper

    return mock, factory


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestBaseColumnarTab:
    """Smoke-тесты BaseColumnarTab."""

    def test_concrete_columnar_tab_basic(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """Конкретный подкласс создаётся с layout_factory, layout корректен."""
        mock, factory = mock_layout
        tab = _ConcreteColumnarTab(
            title="Test Tab",
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        assert isinstance(tab, BaseColumnarTab)
        assert isinstance(tab, QWidget)

        # Layout-методы вызваны
        mock.set_title.assert_called_once_with("Test Tab")
        assert mock.set_nav_widget.call_count == 1
        assert mock.set_content_widget.call_count == 1

    def test_concrete_with_diff_scroll_layout(
        self,
        qtbot,
    ) -> None:
        """Конкретный подкласс работает с реальным DiffScrollTabLayout."""
        tab = _ConcreteColumnarTab(
            title="Real Layout",
            ctx=None,
            layout_factory=lambda: DiffScrollTabLayout(title="Test"),
        )
        qtbot.addWidget(tab)

        assert isinstance(tab, BaseColumnarTab)
        assert isinstance(tab._tab_layout, DiffScrollTabLayout)

    def test_register_content_widget(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """register_content_widget добавляет виджеты в стек с правильными индексами."""
        _, factory = mock_layout
        tab = _ConcreteColumnarTab(
            title="Test",
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        idx_a = tab.register_content_widget("a", QLabel("A"))
        idx_b = tab.register_content_widget("b", QLabel("B"))

        assert idx_a == 0
        assert idx_b == 1
        assert tab._content_stack.count() == 2

    def test_select_key_switches_stack(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """select_key переключает стек и эмитит section_changed."""
        _, factory = mock_layout
        tab = _ConcreteColumnarTab(
            title="Test",
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        tab.register_content_widget("a", QLabel("A"))
        tab.register_content_widget("b", QLabel("B"))

        # Перехватываем сигнал
        with qtbot.waitSignal(tab.section_changed, timeout=1000) as blocker:
            tab.select_key("b")

        assert tab._content_stack.currentIndex() == 1
        assert blocker.args == ["b"]

    def test_select_key_unknown_raises_key_error(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """select_key с незарегистрированным ключом вызывает KeyError."""
        _, factory = mock_layout
        tab = _ConcreteColumnarTab(
            title="Test",
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        with pytest.raises(KeyError, match="unknown"):
            tab.select_key("unknown")

    def test_no_layout_factory_raises_runtime_error(self) -> None:
        """Без layout_factory --- RuntimeError."""
        with pytest.raises(RuntimeError, match="layout_factory обязателен"):
            _ConcreteColumnarTab(
                title="Test",
                ctx=None,
                layout_factory=None,
            )


class TestBaseColumnarTabIsolation:
    """Проверка изоляции BaseColumnarTab от SectionSpec-зависимостей."""

    def test_base_columnar_tab_imports_without_section_spec(self) -> None:
        """Модуль base_columnar_tab НЕ содержит SectionSpec/TreeNavTabPresenter.

        Pure-Python тест (без Qt) --- проверяет только содержимое модуля.
        """
        import multiprocess_framework.modules.frontend_module.widgets.tabs.base_columnar_tab as mod

        source_names = dir(mod)
        # НЕ должно быть SectionSpec-зависимостей
        forbidden = {"SectionSpec", "SectionProtocol", "TreeNavTabPresenter"}
        found = forbidden & set(source_names)
        assert found == set(), f"BaseColumnarTab импортирует запрещённые имена: {found}"
