"""Тесты для TabFactory, LazyTabWidget, PlaceholderTab."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QTabWidget, QWidget

from multiprocess_prototype.frontend.tab_factory import (
    TAB_ORDER,
    LazyTabWidget,
    TabFactory,
)
from multiprocess_prototype.frontend.widgets.tabs.placeholder import PlaceholderTab


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


def _make_ctx() -> MagicMock:
    """Создать mock AppContext."""
    ctx = MagicMock()
    return ctx


# ---------------------------------------------------------------------------
# Тесты PlaceholderTab
# ---------------------------------------------------------------------------


class TestPlaceholderTab:
    """Тесты заглушки таба."""

    def test_creation(self, qtbot):
        """PlaceholderTab создаётся без ошибок."""
        tab = PlaceholderTab(tab_id="settings", title="Settings")
        qtbot.addWidget(tab)
        assert tab.tab_id == "settings"

    def test_object_name(self, qtbot):
        """objectName формируется по шаблону PlaceholderTab_{tab_id}."""
        tab = PlaceholderTab(tab_id="recipes", title="Recipes")
        qtbot.addWidget(tab)
        assert tab.objectName() == "PlaceholderTab_recipes"

    def test_tab_id_property(self, qtbot):
        """tab_id возвращает переданный идентификатор."""
        tab = PlaceholderTab(tab_id="pipeline", title="Pipeline", description="Desc")
        qtbot.addWidget(tab)
        assert tab.tab_id == "pipeline"

    def test_description_in_title(self, qtbot):
        """description не приводит к ошибке при создании."""
        tab = PlaceholderTab(tab_id="displays", title="Displays", description="Some desc")
        qtbot.addWidget(tab)
        assert tab.tab_id == "displays"


# ---------------------------------------------------------------------------
# Тесты TabFactory.create_tabs
# ---------------------------------------------------------------------------


class TestTabFactoryCreateTabs:
    """Тесты метода create_tabs."""

    def test_creates_7_tabs(self, qtbot):
        """create_tabs добавляет ровно 7 табов в QTabWidget."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)
        ctx = _make_ctx()

        factory = TabFactory(ctx)
        factory.create_tabs(tab_widget)

        assert tab_widget.count() == 7

    def test_tab_order(self, qtbot):
        """Табы идут в порядке: Settings → Recipes → Processes → Services → Plugins → Pipeline → Displays."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        factory = TabFactory(_make_ctx())
        factory.create_tabs(tab_widget)

        expected_titles = ["Settings", "Recipes", "Processes", "Services", "Plugins", "Pipeline", "Displays"]
        actual_titles = [tab_widget.tabText(i) for i in range(tab_widget.count())]
        assert actual_titles == expected_titles

    def test_default_tabs_are_placeholders(self, qtbot):
        """Все табы без custom_factories — PlaceholderTab."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        factory = TabFactory(_make_ctx())
        factory.create_tabs(tab_widget)

        for i in range(tab_widget.count()):
            widget = tab_widget.widget(i)
            assert isinstance(widget, PlaceholderTab), (
                f"Таб {i} ({tab_widget.tabText(i)}) должен быть PlaceholderTab, "
                f"но является {type(widget).__name__}"
            )

    def test_placeholder_tab_ids_match_order(self, qtbot):
        """tab_id каждого PlaceholderTab совпадает с id из TAB_ORDER."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        factory = TabFactory(_make_ctx())
        factory.create_tabs(tab_widget)

        for i, tab_info in enumerate(TAB_ORDER):
            widget = tab_widget.widget(i)
            assert isinstance(widget, PlaceholderTab)
            assert widget.tab_id == tab_info["id"]

    def test_custom_factory_overrides_tab(self, qtbot):
        """custom_factories заменяет заглушку на LazyTabWidget."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        mock_widget = QWidget()
        qtbot.addWidget(mock_widget)
        settings_factory = MagicMock(return_value=mock_widget)

        factory = TabFactory(_make_ctx(), custom_factories={"settings": settings_factory})
        factory.create_tabs(tab_widget)

        # Первый таб — settings — должен быть LazyTabWidget (не PlaceholderTab)
        settings_tab = tab_widget.widget(0)
        assert isinstance(settings_tab, LazyTabWidget)

        # Остальные табы — PlaceholderTab
        for i in range(1, tab_widget.count()):
            assert isinstance(tab_widget.widget(i), PlaceholderTab)


# ---------------------------------------------------------------------------
# Тесты LazyTabWidget
# ---------------------------------------------------------------------------


class TestLazyTabWidget:
    """Тесты ленивой инициализации."""

    def test_factory_not_called_before_show(self, qtbot):
        """factory_fn не вызывается до showEvent."""
        factory_fn = MagicMock(return_value=QWidget())
        lazy = LazyTabWidget(factory_fn)
        qtbot.addWidget(lazy)

        factory_fn.assert_not_called()

    def test_factory_called_on_first_show(self, qtbot):
        """factory_fn вызывается при первом show."""
        inner_widget = QWidget()
        factory_fn = MagicMock(return_value=inner_widget)
        lazy = LazyTabWidget(factory_fn)
        qtbot.addWidget(lazy)

        lazy.show()

        factory_fn.assert_called_once()

    def test_factory_called_only_once(self, qtbot):
        """factory_fn вызывается ровно один раз, даже при повторных show."""
        factory_fn = MagicMock(return_value=QWidget())
        lazy = LazyTabWidget(factory_fn)
        qtbot.addWidget(lazy)

        lazy.show()
        lazy.hide()
        lazy.show()

        factory_fn.assert_called_once()

    def test_factory_error_shows_error_label(self, qtbot):
        """При исключении в factory создаётся QLabel с текстом ошибки."""
        def bad_factory():
            raise RuntimeError("Тестовая ошибка")

        lazy = LazyTabWidget(bad_factory)
        qtbot.addWidget(lazy)
        lazy.show()  # не должно выбросить исключение наружу

        # После show виджет должен быть жив — ошибка поглощена
        assert lazy.isVisible()

    def test_factory_returns_none_no_widget_added(self, qtbot):
        """Если factory возвращает None — лишних виджетов не добавляется."""
        factory_fn = MagicMock(return_value=None)
        lazy = LazyTabWidget(factory_fn)
        qtbot.addWidget(lazy)
        lazy.show()

        factory_fn.assert_called_once()
        # Виджет живой, ошибок нет
        assert lazy.isVisible()


# ---------------------------------------------------------------------------
# Тесты TabFactory.create_tab (единичная фабрикация)
# ---------------------------------------------------------------------------


class TestTabFactoryCreateTab:
    """Тесты метода create_tab."""

    def test_unknown_id_returns_none(self, qtbot):
        """create_tab с неизвестным id возвращает None."""
        factory = TabFactory(_make_ctx())
        result = factory.create_tab("nonexistent_tab")
        assert result is None

    def test_known_id_without_custom_factory_returns_placeholder(self, qtbot):
        """create_tab для известного id без custom factory → PlaceholderTab."""
        factory = TabFactory(_make_ctx())
        result = factory.create_tab("settings")
        if result is not None:
            qtbot.addWidget(result)
        assert isinstance(result, PlaceholderTab)
        assert result.tab_id == "settings"

    def test_custom_factory_called_directly(self, qtbot):
        """create_tab вызывает custom factory напрямую (без LazyTabWidget)."""
        custom_widget = QWidget()
        qtbot.addWidget(custom_widget)
        factory_fn = MagicMock(return_value=custom_widget)

        ctx = _make_ctx()
        factory = TabFactory(ctx, custom_factories={"recipes": factory_fn})
        result = factory.create_tab("recipes")

        factory_fn.assert_called_once_with(ctx)
        assert result is custom_widget

    def test_custom_factory_returns_none_falls_back_to_placeholder(self, qtbot):
        """Если custom factory вернула None — используется PlaceholderTab."""
        factory_fn = MagicMock(return_value=None)
        factory = TabFactory(_make_ctx(), custom_factories={"processes": factory_fn})

        result = factory.create_tab("processes")
        if result is not None:
            qtbot.addWidget(result)

        assert isinstance(result, PlaceholderTab)
        assert result.tab_id == "processes"

    def test_custom_factory_raises_falls_back_to_placeholder(self, qtbot):
        """Если custom factory выбросила исключение — используется PlaceholderTab."""
        def bad_factory(ctx):
            raise ValueError("Намеренная ошибка")

        factory = TabFactory(_make_ctx(), custom_factories={"plugins": bad_factory})
        result = factory.create_tab("plugins")
        if result is not None:
            qtbot.addWidget(result)

        assert isinstance(result, PlaceholderTab)
        assert result.tab_id == "plugins"

    def test_all_known_ids_return_widget(self, qtbot):
        """create_tab для всех известных id возвращает QWidget (не None)."""
        factory = TabFactory(_make_ctx())
        for tab_info in TAB_ORDER:
            result = factory.create_tab(tab_info["id"])
            assert result is not None, f"create_tab({tab_info['id']!r}) вернул None"
            qtbot.addWidget(result)
            assert isinstance(result, QWidget)
