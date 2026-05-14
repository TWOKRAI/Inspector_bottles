"""Тесты для SideNavLayout — универсальная боковая навигация."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

from multiprocess_prototype.frontend.widgets.primitives import SideNavLayout


class TestSideNavLayout:
    """Тесты SideNavLayout."""

    def _make(self, qtbot, **kwargs) -> SideNavLayout:
        w = SideNavLayout(**kwargs)
        qtbot.addWidget(w)
        return w

    def test_add_section_adds_to_list(self, qtbot):
        nav = self._make(qtbot)
        nav.add_section("a", "Alpha", QWidget())
        nav.add_section("b", "Beta", QWidget())
        nav.add_section("c", "Gamma", QWidget())
        assert nav._nav_list.count() == 3

    def test_set_current_switches_key(self, qtbot):
        nav = self._make(qtbot)
        nav.add_section("a", "Alpha", QWidget())
        nav.add_section("b", "Beta", QWidget())
        nav.set_current("b")
        assert nav.current_key() == "b"

    def test_set_current_switches_stack(self, qtbot):
        nav = self._make(qtbot)
        w_a = QLabel("A")
        w_b = QLabel("B")
        nav.add_section("a", "Alpha", w_a)
        nav.add_section("b", "Beta", w_b)
        nav.set_current("b")
        assert nav._stack.currentWidget() is w_b

    def test_section_changed_signal(self, qtbot):
        nav = self._make(qtbot)
        nav.add_section("a", "Alpha", QWidget())
        nav.add_section("b", "Beta", QWidget())
        nav.set_current("a")

        with qtbot.waitSignal(nav.section_changed, timeout=1000) as blocker:
            nav.set_current("b")
        assert blocker.args == ["b"]

    def test_current_key_empty_when_no_sections(self, qtbot):
        nav = self._make(qtbot)
        assert nav.current_key() == ""

    def test_custom_nav_width(self, qtbot):
        nav = self._make(qtbot, nav_width=300)
        assert nav._nav_list.maximumWidth() == 300

    def test_default_nav_width(self, qtbot):
        nav = self._make(qtbot)
        assert nav._nav_list.maximumWidth() == 200

    def test_click_row_switches_content(self, qtbot):
        nav = self._make(qtbot)
        w_a = QLabel("A")
        w_b = QLabel("B")
        nav.add_section("a", "Alpha", w_a)
        nav.add_section("b", "Beta", w_b)

        # Программный клик на вторую строку
        nav._nav_list.setCurrentRow(1)
        assert nav.current_key() == "b"
        assert nav._stack.currentWidget() is w_b

    def test_set_current_invalid_key_no_crash(self, qtbot):
        nav = self._make(qtbot)
        nav.add_section("a", "Alpha", QWidget())
        nav.set_current("a")
        # Несуществующий ключ — ничего не меняется
        nav.set_current("nonexistent")
        assert nav.current_key() == "a"
