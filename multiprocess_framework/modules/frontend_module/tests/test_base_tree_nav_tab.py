# -*- coding: utf-8 -*-
"""Тесты BaseTreeNavTab --- smoke-тесты с pytest-qt.

Проверяют: построение UI по SectionSpec, навигацию, ретрансляцию
событий секций, ленивое создание, переопределение objectName.

См. ADR-126, Phase 3.
"""

from __future__ import annotations

from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    BaseTreeNavTab,
    SectionSpec,
    TabLayoutProtocol,
)


# ---------------------------------------------------------------------------
# Фейковые секции
# ---------------------------------------------------------------------------


class _FakeSection:
    """Минимальная секция, удовлетворяющая SectionProtocol."""

    def __init__(self, key: str, title: str = "Section") -> None:
        self._key = key
        self._title = title
        self._widget = QLabel(f"Content: {key}")
        self._btn = QPushButton(f"Action: {key}")
        self.activated = False
        self.deactivated = False

    @property
    def key(self) -> str:
        return self._key

    @property
    def title(self) -> str:
        return self._title

    def widget(self) -> QWidget:
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return [self._btn]

    def on_activated(self) -> None:
        self.activated = True

    def on_deactivated(self) -> None:
        self.deactivated = True


class _FakeSectionWithEvents(_FakeSection):
    """Секция с SectionWithEvents-совместимыми атрибутами (Qt-сигналы)."""

    # Эмитим через промежуточный QWidget, потому что Signal
    # нужен в QObject-наследнике.
    pass


class _SignalHolder(QWidget):
    """QWidget-обёртка для Qt-сигналов (нельзя объявить Signal на plain class)."""

    section_dirty_changed = Signal(bool)
    section_data_saved = Signal(dict)

    def __init__(self, bus_cb: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._bus_cb = bus_cb

    def bus_change_callback(self) -> Callable[[], None] | None:
        return self._bus_cb


class _FakeEventSection:
    """Секция с событиями через отдельный signal holder."""

    def __init__(
        self,
        key: str,
        title: str = "EventSection",
        bus_cb: Callable[[], None] | None = None,
    ) -> None:
        self._key = key
        self._title = title
        self._widget = QLabel(f"Content: {key}")
        self._holder = _SignalHolder(bus_cb)
        # Прокидываем сигналы как атрибуты секции (structural duck-typing)
        self.section_dirty_changed = self._holder.section_dirty_changed
        self.section_data_saved = self._holder.section_data_saved

    @property
    def key(self) -> str:
        return self._key

    @property
    def title(self) -> str:
        return self._title

    def widget(self) -> QWidget:
        return self._widget

    def action_buttons(self) -> list[QWidget]:
        return []

    def on_activated(self) -> None:
        pass

    def on_deactivated(self) -> None:
        pass

    def bus_change_callback(self) -> Callable[[], None] | None:
        return self._holder.bus_change_callback()

    def emit_dirty(self, dirty: bool) -> None:
        """Хелпер для теста: эмитить dirty сигнал."""
        self._holder.section_dirty_changed.emit(dirty)

    def emit_saved(self, data: dict) -> None:
        """Хелпер для теста: эмитить saved сигнал."""
        self._holder.section_data_saved.emit(data)


# ---------------------------------------------------------------------------
# Фабрика мок-layout'а
# ---------------------------------------------------------------------------


def _make_mock_layout() -> MagicMock:
    """Создать мок-layout, удовлетворяющий TabLayoutProtocol."""
    mock = MagicMock(spec=TabLayoutProtocol)
    # Мок — QWidget-совместимый для addWidget в QVBoxLayout
    # Подсунем реальный QWidget вместо мока
    mock_widget = QWidget()
    # Чтобы main_layout.addWidget(self._layout) не падал —
    # делаем мок callable, а результат — реальный QWidget
    return mock, mock_widget


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
# Fixtures
# ---------------------------------------------------------------------------


def _section_factory(key: str, title: str) -> Callable[[Any], _FakeSection]:
    """Фабрика, создающая _FakeSection по контексту."""

    def factory(ctx: Any) -> _FakeSection:
        return _FakeSection(key, title)

    return factory


@pytest.fixture
def two_specs() -> list[SectionSpec]:
    """Две top-level секции."""
    return [
        SectionSpec("alpha", "Alpha Section", _section_factory("alpha", "Alpha Section")),
        SectionSpec("beta", "Beta Section", _section_factory("beta", "Beta Section")),
    ]


@pytest.fixture
def mock_layout() -> tuple[MagicMock, Callable[[], _MockLayoutWrapper]]:
    """Мок-layout и фабрика."""
    mock = MagicMock()
    wrapper = _MockLayoutWrapper(mock)

    def factory() -> _MockLayoutWrapper:
        return wrapper

    return mock, factory


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestBaseTreeNavTab:
    """Smoke-тесты BaseTreeNavTab."""

    def test_builds_with_two_sections(
        self,
        qtbot,
        two_specs,
        mock_layout,
    ) -> None:
        """BaseTreeNavTab с 2 секциями: layout-методы вызваны, tree содержит 2 элемента."""
        mock, factory = mock_layout
        tab = BaseTreeNavTab(
            title="Test Tab",
            sections=two_specs,
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        # Layout-методы вызваны
        mock.set_title.assert_called_once_with("Test Tab")
        assert mock.set_action_widget.call_count == 1
        assert mock.set_nav_widget.call_count == 1
        assert mock.set_content_widget.call_count == 1
        assert mock.connect_stack.call_count == 2  # content + action

        # Nav tree содержит 2 top-level элемента
        root = tab.tree_nav.invisibleRootItem()
        assert root.childCount() == 2
        assert root.child(0).data(0, Qt.ItemDataRole.UserRole) == "alpha"
        assert root.child(1).data(0, Qt.ItemDataRole.UserRole) == "beta"

    def test_section_changed_signal_emits_on_navigation(
        self,
        qtbot,
        two_specs,
        mock_layout,
    ) -> None:
        """Переключение секции эмитит section_changed с правильным key."""
        _, factory = mock_layout
        tab = BaseTreeNavTab(
            title="Test",
            sections=two_specs,
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        with qtbot.waitSignal(tab.section_changed, timeout=1000) as blocker:
            # Программно выбрать вторую секцию в дереве
            root = tab.tree_nav.invisibleRootItem()
            tab.tree_nav.setCurrentItem(root.child(1))

        assert blocker.args == ["beta"]

    def test_section_dirty_changed_proxied(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """Сигнал section_dirty_changed секции ретранслируется табом."""
        event_section = _FakeEventSection("sys", "System")

        specs = [
            SectionSpec("sys", "System", lambda ctx: event_section),
        ]
        _, factory = mock_layout
        tab = BaseTreeNavTab(
            title="Test",
            sections=specs,
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        with qtbot.waitSignal(tab.section_dirty_changed, timeout=1000) as blocker:
            event_section.emit_dirty(True)

        assert blocker.args == ["sys", True]

    def test_section_data_saved_proxied(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """Сигнал section_data_saved секции ретранслируется табом."""
        event_section = _FakeEventSection("sys", "System")

        specs = [
            SectionSpec("sys", "System", lambda ctx: event_section),
        ]
        _, factory = mock_layout
        tab = BaseTreeNavTab(
            title="Test",
            sections=specs,
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        save_data = {"key": "value"}
        with qtbot.waitSignal(tab.section_data_saved, timeout=1000) as blocker:
            event_section.emit_saved(save_data)

        assert blocker.args[0] == "sys"
        assert blocker.args[1] == save_data

    def test_lazy_section_creation_on_navigation(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """Ленивая секция создаётся при первой навигации."""
        factory_calls: list[str] = []

        def lazy_factory(ctx: Any) -> _FakeSection:
            factory_calls.append("called")
            return _FakeSection("lazy_child", "Lazy Child")

        specs = [
            SectionSpec("parent", "Parent", _section_factory("parent", "Parent")),
            SectionSpec(
                "lazy_child",
                "Lazy Child",
                lazy_factory,
                parent_key="parent",
                lazy=True,
            ),
        ]
        _, layout_factory = mock_layout
        tab = BaseTreeNavTab(
            title="Test",
            sections=specs,
            ctx=None,
            layout_factory=layout_factory,
        )
        qtbot.addWidget(tab)

        # Фабрика ещё не вызвана (lazy)
        assert factory_calls == []

        # Навигация к ленивому узлу
        from multiprocess_framework.modules.frontend_module.widgets.tabs.nav_tree_utils import (
            find_tree_item,
        )

        root = tab.tree_nav.invisibleRootItem()
        lazy_item = find_tree_item(root, "lazy_child")
        assert lazy_item is not None
        tab.tree_nav.setCurrentItem(lazy_item)

        # Фабрика вызвана
        assert factory_calls == ["called"]

    def test_bus_change_callback_subscribed_when_subscriber_provided(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """bus_change_subscriber вызывается с callback секции."""
        subscribed_callbacks: list[Callable] = []

        def subscriber(cb: Callable[[], None]) -> None:
            subscribed_callbacks.append(cb)

        my_callback = lambda: None  # noqa: E731
        event_section = _FakeEventSection("sys", "System", bus_cb=my_callback)

        specs = [
            SectionSpec("sys", "System", lambda ctx: event_section),
        ]
        _, factory = mock_layout
        tab = BaseTreeNavTab(
            title="Test",
            sections=specs,
            ctx=None,
            layout_factory=factory,
            bus_change_subscriber=subscriber,
        )
        qtbot.addWidget(tab)

        assert len(subscribed_callbacks) == 1
        assert subscribed_callbacks[0] is my_callback

    def test_tree_object_name_overridable(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """Наследник может переопределить _tree_object_name()."""

        class _CustomTab(BaseTreeNavTab):
            def _tree_object_name(self) -> str:
                return "CustomTreeNav"

        specs = [
            SectionSpec("a", "A", _section_factory("a", "A")),
        ]
        _, factory = mock_layout
        tab = _CustomTab(
            title="Custom",
            sections=specs,
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        assert tab.tree_nav.objectName() == "CustomTreeNav"

    def test_default_tree_object_name(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """По умолчанию objectName = TreeNavWidget."""
        specs = [
            SectionSpec("a", "A", _section_factory("a", "A")),
        ]
        _, factory = mock_layout
        tab = BaseTreeNavTab(
            title="Test",
            sections=specs,
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        assert tab.tree_nav.objectName() == "TreeNavWidget"

    def test_no_layout_factory_raises_runtime_error(self) -> None:
        """Без layout_factory — RuntimeError."""
        specs = [
            SectionSpec("a", "A", _section_factory("a", "A")),
        ]
        with pytest.raises(RuntimeError, match="layout_factory обязателен"):
            BaseTreeNavTab(
                title="Test",
                sections=specs,
                ctx=None,
                layout_factory=None,
            )

    def test_populate_navigates_to_first_section(
        self,
        qtbot,
        mock_layout,
    ) -> None:
        """populate() навигирует к первой top-level секции."""
        _, factory = mock_layout
        tab = BaseTreeNavTab(
            title="Test",
            sections=[
                SectionSpec("first", "First", _section_factory("first", "First")),
                SectionSpec("second", "Second", _section_factory("second", "Second")),
            ],
            ctx=None,
            layout_factory=factory,
        )
        qtbot.addWidget(tab)

        with qtbot.waitSignal(tab.section_changed, timeout=1000) as blocker:
            tab.populate()

        assert blocker.args == ["first"]
