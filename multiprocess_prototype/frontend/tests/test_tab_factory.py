"""Тесты для TabFactory, LazyTabWidget, PlaceholderTab."""

from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QTabWidget, QWidget

from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.tab_factory import (
    TAB_ORDER,
    LazyTabWidget,
    TabFactory,
)
from multiprocess_prototype.frontend.widgets.tabs.placeholder import PlaceholderTab


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


def _make_tab_factory(
    auth_state: object | None = None,
    custom_factories: dict | None = None,
) -> TabFactory:
    """Создать TabFactory с explicit (app_services, auth_ctx, runtime).

    G.5.2: TabFactory принимает explicit аргументы вместо AppContext.
    По умолчанию `auth_ctx` is None — фабрика работает в legacy-режиме
    без фильтрации по permissions (все табы видны). Для тестов фильтрации
    передавай stub AuthState с атрибутом `access_context` и сигналом
    `access_context_changed`.
    """
    from multiprocess_prototype.domain.tests.conftest import make_test_app_services

    app_services = make_test_app_services()
    if auth_state is None:
        auth_ctx = None
    else:
        auth_ctx = MagicMock()
        auth_ctx.state = auth_state
    return TabFactory(
        app_services,
        auth_ctx=auth_ctx,
        runtime=RuntimeDeps(),
        custom_factories=custom_factories,
    )


class _StubAuthState(QObject):
    """Минимальный AuthState для тестов: только сигнал и access_context."""

    access_context_changed = Signal(AccessContext)

    def __init__(self, ctx: AccessContext | None = None) -> None:
        super().__init__()
        self.access_context: AccessContext = ctx or AccessContext()

    def set_context(self, ctx: AccessContext) -> None:
        self.access_context = ctx
        self.access_context_changed.emit(ctx)


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

        factory = _make_tab_factory()
        factory.create_tabs(tab_widget)

        assert tab_widget.count() == 7

    def test_tab_order(self, qtbot):
        """Табы идут в порядке: Settings → Recipes → Processes → Services → Plugins → Pipeline → Displays."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        factory = _make_tab_factory()
        factory.create_tabs(tab_widget)

        expected_titles = ["Settings", "Recipes", "Processes", "Services", "Plugins", "Pipeline", "Displays"]
        actual_titles = [tab_widget.tabText(i) for i in range(tab_widget.count())]
        assert actual_titles == expected_titles

    def test_default_tabs_are_placeholders(self, qtbot):
        """Все табы без custom_factories — PlaceholderTab."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        factory = _make_tab_factory()
        factory.create_tabs(tab_widget)

        for i in range(tab_widget.count()):
            widget = tab_widget.widget(i)
            assert isinstance(widget, PlaceholderTab), (
                f"Таб {i} ({tab_widget.tabText(i)}) должен быть PlaceholderTab, но является {type(widget).__name__}"
            )

    def test_placeholder_tab_ids_match_order(self, qtbot):
        """tab_id каждого PlaceholderTab совпадает с id из TAB_ORDER."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        factory = _make_tab_factory()
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

        factory = _make_tab_factory(custom_factories={"settings": settings_factory})
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
        factory = _make_tab_factory()
        result = factory.create_tab("nonexistent_tab")
        assert result is None

    def test_known_id_without_custom_factory_returns_placeholder(self, qtbot):
        """create_tab для известного id без custom factory → PlaceholderTab."""
        factory = _make_tab_factory()
        result = factory.create_tab("settings")
        if result is not None:
            qtbot.addWidget(result)
        assert isinstance(result, PlaceholderTab)
        assert result.tab_id == "settings"

    def test_custom_factory_called_directly(self, qtbot):
        """create_tab вызывает custom factory напрямую (без LazyTabWidget).

        G.5.2: factory получает (app_services, RuntimeDeps).
        """
        custom_widget = QWidget()
        qtbot.addWidget(custom_widget)
        factory_fn = MagicMock(return_value=custom_widget)

        factory = _make_tab_factory(custom_factories={"recipes": factory_fn})
        result = factory.create_tab("recipes")

        factory_fn.assert_called_once_with(factory._services, factory._runtime)
        assert result is custom_widget

    def test_custom_factory_returns_none_falls_back_to_placeholder(self, qtbot):
        """Если custom factory вернула None — используется PlaceholderTab."""
        factory_fn = MagicMock(return_value=None)
        factory = _make_tab_factory(custom_factories={"processes": factory_fn})

        result = factory.create_tab("processes")
        if result is not None:
            qtbot.addWidget(result)

        assert isinstance(result, PlaceholderTab)
        assert result.tab_id == "processes"

    def test_custom_factory_raises_falls_back_to_placeholder(self, qtbot):
        """Если custom factory выбросила исключение — используется PlaceholderTab."""

        def bad_factory(services, runtime):
            raise ValueError("Намеренная ошибка")

        factory = _make_tab_factory(custom_factories={"plugins": bad_factory})
        result = factory.create_tab("plugins")
        if result is not None:
            qtbot.addWidget(result)

        assert isinstance(result, PlaceholderTab)
        assert result.tab_id == "plugins"

    def test_all_known_ids_return_widget(self, qtbot):
        """create_tab для всех известных id возвращает QWidget (не None)."""
        factory = _make_tab_factory()
        for tab_info in TAB_ORDER:
            result = factory.create_tab(tab_info["id"])
            assert result is not None, f"create_tab({tab_info['id']!r}) вернул None"
            qtbot.addWidget(result)
            assert isinstance(result, QWidget)


# ---------------------------------------------------------------------------
# Тесты фильтрации по permissions
# ---------------------------------------------------------------------------


def _visible_tab_ids(tab_widget: QTabWidget) -> list[str]:
    """Список id видимых табов в порядке TAB_ORDER."""
    bar = tab_widget.tabBar()
    visible: list[str] = []
    for i, tab_info in enumerate(TAB_ORDER):
        if bar.isTabVisible(i):
            visible.append(tab_info["id"])
    return visible


class TestTabFactoryPermissions:
    """Фильтрация по `view_permission` из TAB_ORDER через QTabBar.setTabVisible."""

    def test_legacy_no_auth_state_shows_all(self, qtbot):
        """Без AuthState (legacy) все табы остаются видимыми."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        factory = _make_tab_factory(auth_state=None)
        factory.create_tabs(tab_widget)

        assert _visible_tab_ids(tab_widget) == [t["id"] for t in TAB_ORDER]

    def test_empty_permissions_hides_all_tabs(self, qtbot):
        """Свежий AccessContext без permissions скрывает все табы с view_permission."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        stub = _StubAuthState()  # default AccessContext() — permissions=frozenset()
        factory = _make_tab_factory(auth_state=stub)
        factory.create_tabs(tab_widget)

        # Все 7 табов имеют view_permission → ни один не виден
        assert _visible_tab_ids(tab_widget) == []

    def test_partial_permissions_shows_subset(self, qtbot):
        """Permissions содержат подмножество view → видны только разрешённые табы."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        ctx = AccessContext(
            permissions=frozenset({"tabs.recipes.view", "tabs.pipeline.view"}),
            role_name="viewer",
        )
        stub = _StubAuthState(ctx)
        factory = _make_tab_factory(auth_state=stub)
        factory.create_tabs(tab_widget)

        assert _visible_tab_ids(tab_widget) == ["recipes", "pipeline"]

    def test_wildcard_permission_shows_all(self, qtbot):
        """Wildcard `*` в permissions делает все табы видимыми (роль dev)."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        ctx = AccessContext(permissions=frozenset({"*"}), role_name="dev")
        stub = _StubAuthState(ctx)
        factory = _make_tab_factory(auth_state=stub)
        factory.create_tabs(tab_widget)

        assert _visible_tab_ids(tab_widget) == [t["id"] for t in TAB_ORDER]

    def test_access_context_changed_reapplies_filter(self, qtbot):
        """Сигнал access_context_changed → пере-применение фильтра."""
        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)

        stub = _StubAuthState()  # старт без permissions
        factory = _make_tab_factory(auth_state=stub)
        factory.create_tabs(tab_widget)
        assert _visible_tab_ids(tab_widget) == []

        # Логин: admin получает recipes + settings
        new_ctx = AccessContext(
            permissions=frozenset({"tabs.recipes.view", "tabs.settings.view"}),
            role_name="admin",
        )
        stub.set_context(new_ctx)

        assert _visible_tab_ids(tab_widget) == ["settings", "recipes"]

        # Logout: возвращаемся к пустому контексту
        stub.set_context(AccessContext())
        assert _visible_tab_ids(tab_widget) == []
