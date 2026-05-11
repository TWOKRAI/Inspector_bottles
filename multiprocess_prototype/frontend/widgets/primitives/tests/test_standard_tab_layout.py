"""Тесты для StandardTabLayout — единый шаблон вкладок."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel, QWidget

from multiprocess_prototype.frontend.widgets.primitives import StandardTabLayout


class _FakeBus:
    """Минимальная заглушка ActionBus для unit-тестов."""

    def __init__(self) -> None:
        self._can_undo = False
        self._can_redo = False
        self._callbacks: list = []
        self.undo_calls = 0
        self.redo_calls = 0

    def can_undo(self) -> bool:
        return self._can_undo

    def can_redo(self) -> bool:
        return self._can_redo

    def add_change_callback(self, cb) -> None:
        self._callbacks.append(cb)

    def undo(self) -> None:
        self.undo_calls += 1

    def redo(self) -> None:
        self.redo_calls += 1

    def _fire(self) -> None:
        for cb in self._callbacks:
            cb()


class TestActionsColumn:
    """Левая колонка: top/bottom actions."""

    def test_add_top_action_creates_button(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))

        btn = layout.add_top_action("save", "Сохранить")
        assert btn.text() == "Сохранить"
        assert layout.get_button("save") is btn

    def test_add_bottom_action_creates_button(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))

        btn = layout.add_bottom_action("clear", "Очистить")
        assert btn.text() == "Очистить"
        assert layout.get_button("clear") is btn

    def test_action_triggered_signal_emits_id(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))
        btn = layout.add_top_action("save", "Сохранить")

        with qtbot.waitSignal(layout.action_triggered, timeout=500) as sig:
            btn.click()
        assert sig.args == ["save"]

    def test_set_action_enabled(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))
        btn = layout.add_top_action("save", "Сохранить")

        layout.set_action_enabled("save", False)
        assert not btn.isEnabled()
        layout.set_action_enabled("save", True)
        assert btn.isEnabled()


class TestUndoRedo:
    """Bottom Undo/Redo через enable_undo_redo()."""

    def test_undo_redo_buttons_disabled_initially(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))

        bus = _FakeBus()
        layout.enable_undo_redo(bus)

        assert layout.undo_button is not None
        assert layout.redo_button is not None
        assert not layout.undo_button.isEnabled()
        assert not layout.redo_button.isEnabled()

    def test_undo_redo_state_reflects_bus(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))

        bus = _FakeBus()
        layout.enable_undo_redo(bus)

        bus._can_undo = True
        bus._fire()
        assert layout.undo_button.isEnabled()
        assert not layout.redo_button.isEnabled()

        bus._can_redo = True
        bus._fire()
        assert layout.redo_button.isEnabled()

    def test_undo_button_calls_bus_undo(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))

        bus = _FakeBus()
        layout.enable_undo_redo(bus)
        bus._can_undo = True
        bus._fire()

        layout.undo_button.click()
        assert bus.undo_calls == 1

    def test_redo_button_calls_bus_redo(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))

        bus = _FakeBus()
        layout.enable_undo_redo(bus)
        bus._can_redo = True
        bus._fire()

        layout.redo_button.click()
        assert bus.redo_calls == 1

    def test_enable_undo_redo_idempotent(self, qtbot):
        """Повторный вызов enable_undo_redo не плодит кнопки."""
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))

        bus = _FakeBus()
        layout.enable_undo_redo(bus)
        first_undo = layout.undo_button
        layout.enable_undo_redo(bus)
        assert layout.undo_button is first_undo

    def test_enable_undo_redo_with_none_bus(self, qtbot):
        """Безопасно при bus=None: кнопки появляются, но disabled."""
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        layout.set_content_widget(QLabel("content"))

        layout.enable_undo_redo(None)
        assert layout.undo_button is not None
        assert not layout.undo_button.isEnabled()
        # Клик не должен падать
        layout.undo_button.click()


class TestSubNav:
    """Sub-nav колонка."""

    def test_sub_nav_present_by_default(self, qtbot):
        layout = StandardTabLayout()
        qtbot.addWidget(layout)
        assert layout.sub_nav_list is not None
        # content_stack создаётся лениво при первом add_sub_nav_section с widget'ом
        assert layout.content_stack is None

    def test_content_stack_created_lazily(self, qtbot):
        layout = StandardTabLayout()
        qtbot.addWidget(layout)
        layout.add_sub_nav_section("a", "Alpha", QLabel("A"))
        assert layout.content_stack is not None

    def test_sub_nav_disabled_via_flag(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        assert layout.sub_nav_list is None
        assert layout.content_stack is None

    def test_add_sub_nav_section_increments_count(self, qtbot):
        layout = StandardTabLayout()
        qtbot.addWidget(layout)
        layout.add_sub_nav_section("a", "Alpha", QLabel("A"))
        layout.add_sub_nav_section("b", "Beta", QLabel("B"))
        assert layout.sub_nav_count() == 2

    def test_set_current_section_emits_signal(self, qtbot):
        layout = StandardTabLayout()
        qtbot.addWidget(layout)
        layout.add_sub_nav_section("a", "Alpha", QLabel("A"))
        layout.add_sub_nav_section("b", "Beta", QLabel("B"))

        with qtbot.waitSignal(layout.section_changed, timeout=500) as sig:
            layout.set_current_section("b")
        assert sig.args == ["b"]
        assert layout.current_section_key() == "b"

    def test_set_current_section_switches_stack(self, qtbot):
        layout = StandardTabLayout()
        qtbot.addWidget(layout)
        w_a = QLabel("A")
        w_b = QLabel("B")
        layout.add_sub_nav_section("a", "Alpha", w_a)
        layout.add_sub_nav_section("b", "Beta", w_b)
        layout.set_current_section("b")
        assert layout.content_stack.currentWidget() is w_b

    def test_clear_sub_nav_resets_count(self, qtbot):
        layout = StandardTabLayout()
        qtbot.addWidget(layout)
        layout.add_sub_nav_section("a", "Alpha", QLabel("A"))
        layout.add_sub_nav_section("b", "Beta", QLabel("B"))
        layout.clear_sub_nav()
        assert layout.sub_nav_count() == 0
        assert layout.current_section_key() == ""


class TestContentWithoutSubNav:
    """show_sub_nav=False — задаём контент через set_content_widget."""

    def test_set_content_widget_attaches_to_scroll(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        content = QLabel("plain content")
        layout.set_content_widget(content)
        assert layout.scroll_area.widget() is content

    def test_set_content_widget_allowed_with_sub_nav(self, qtbot):
        """В sub-nav-режиме set_content_widget — это external-content паттерн."""
        layout = StandardTabLayout(show_sub_nav=True)
        qtbot.addWidget(layout)
        content = QLabel("shared")
        layout.set_content_widget(content)
        assert layout.scroll_area.widget() is content

    def test_add_sub_nav_disallowed_without_sub_nav(self, qtbot):
        layout = StandardTabLayout(show_sub_nav=False)
        qtbot.addWidget(layout)
        with pytest.raises(AssertionError):
            layout.add_sub_nav_section("a", "Alpha", QLabel("A"))

    def test_external_content_mode_with_sub_nav_keys(self, qtbot):
        """sub-nav без widget + общий content_widget — секции работают как выбор."""
        layout = StandardTabLayout(show_sub_nav=True)
        qtbot.addWidget(layout)
        shared = QLabel("shared")
        layout.set_content_widget(shared)
        layout.add_sub_nav_section("a", "Alpha")
        layout.add_sub_nav_section("b", "Beta")

        seen: list[str] = []
        layout.section_changed.connect(seen.append)
        layout.set_current_section("b")
        assert seen == ["b"]
        assert layout.scroll_area.widget() is shared  # контент не сменился


class TestColumnWidth:
    """Левая колонка имеет фиксированную ширину."""

    def test_default_action_column_width(self, qtbot):
        layout = StandardTabLayout()
        qtbot.addWidget(layout)
        assert layout.action_column.width() == 120

    def test_custom_action_column_width(self, qtbot):
        layout = StandardTabLayout(action_width=180)
        qtbot.addWidget(layout)
        assert layout.action_column.width() == 180
