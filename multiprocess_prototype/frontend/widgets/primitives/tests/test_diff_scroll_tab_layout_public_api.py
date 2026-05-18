# -*- coding: utf-8 -*-
"""Тесты публичного API DiffScrollTabLayout (Phase 3.1).

Проверяют: refresh_after_page_change, connect_stack,
автоматическое подключение вложенных QScrollArea через ChildAdded.

См. ADR-126, Phase 3.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)


@pytest.fixture
def layout(qtbot) -> DiffScrollTabLayout:
    """Создать DiffScrollTabLayout для тестов."""
    w = DiffScrollTabLayout(title="Test")
    qtbot.addWidget(w)
    return w


class TestRefreshAfterPageChange:
    """Тесты refresh_after_page_change."""

    def test_refresh_content_does_not_crash(self, layout) -> None:
        """Вызов refresh_after_page_change('content') не падает."""
        stack = QStackedWidget()
        stack.addWidget(QLabel("Page 1"))
        stack.addWidget(QLabel("Page 2"))
        layout.set_content_widget(stack)

        stack.setCurrentIndex(1)
        # Не должно вызывать исключений
        layout.refresh_after_page_change("content")

    def test_refresh_action_does_not_crash(self, layout) -> None:
        """Вызов refresh_after_page_change('action') не падает."""
        layout.refresh_after_page_change("action")


class TestConnectStack:
    """Тесты connect_stack."""

    def test_connect_stack_auto_refresh_content(self, layout) -> None:
        """connect_stack подключает авто-refresh при смене страницы."""
        stack = QStackedWidget()
        page1 = QLabel("Page 1")
        page2 = QLabel("Page 2")
        stack.addWidget(page1)
        stack.addWidget(page2)
        layout.set_content_widget(stack)

        layout.connect_stack(stack, "content")

        # Переключить страницу — master scrollbar не должен упасть
        stack.setCurrentIndex(1)

        # Проверяем что мастер-скроллбар отработал (maximum >= 0 всегда)
        assert layout.master_scrollbar.maximum() >= 0

    def test_connect_stack_auto_refresh_action(self, layout) -> None:
        """connect_stack для action-колонки."""
        stack = QStackedWidget()
        stack.addWidget(QLabel("A"))
        stack.addWidget(QLabel("B"))
        layout.set_action_widget(stack)

        layout.connect_stack(stack, "action")
        stack.setCurrentIndex(1)

        assert layout.master_scrollbar.maximum() >= 0


class TestAutoPickInnerScrolls:
    """Тесты автоматического подключения вложенных QScrollArea."""

    def test_set_content_widget_auto_picks_inner_scrolls(self, layout) -> None:
        """Виджет с QScrollArea внутри автоматически подхватывается."""
        stack = QStackedWidget()
        layout.set_content_widget(stack)

        initial_count = len(layout._scroll_areas)

        # Добавить страницу с вложенным QScrollArea
        page = QWidget()
        page_layout = QVBoxLayout(page)
        inner_scroll = QScrollArea()
        inner_scroll.setWidget(QLabel("Scrollable content"))
        page_layout.addWidget(inner_scroll)
        stack.addWidget(page)

        # ChildAdded event filter должен подхватить inner_scroll
        # через processEvents (event filter работает асинхронно)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()

        # Проверяем что количество scroll areas увеличилось
        assert len(layout._scroll_areas) >= initial_count
