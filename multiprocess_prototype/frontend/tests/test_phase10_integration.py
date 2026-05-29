"""Smoke test Phase 10 — все 7 табов создаются и работают.

Task F.9: фабрики принимают (AppServices, RuntimeDeps).
G.5.3: TabFactory принимает explicit (app_services, auth_ctx, runtime) — без AppContext.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from multiprocess_prototype.frontend.tab_factory import TabFactory, TAB_ORDER
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.widgets.tabs import register_all_tabs
from multiprocess_prototype.frontend.widgets.tabs.placeholder import PlaceholderTab


def _make_app_services():
    """Реальный AppServices через builder для smoke-тестов."""
    from multiprocess_prototype.domain.tests.conftest import make_test_app_services

    return make_test_app_services()


class TestPhase10Integration:
    """Smoke-тесты интеграции всех табов Phase 10."""

    def test_register_all_tabs_returns_7(self):
        """register_all_tabs() возвращает dict с 7 factory functions."""
        factories = register_all_tabs()
        assert len(factories) == 7
        for tab_info in TAB_ORDER:
            assert tab_info["id"] in factories, f"Таб '{tab_info['id']}' не зарегистрирован"

    def test_all_tabs_creatable(self, qtbot):
        """Каждый таб создаётся без исключений через create(services, runtime)."""
        from multiprocess_prototype.domain.tests.conftest import make_test_app_services

        services = make_test_app_services()
        runtime = RuntimeDeps()
        factories = register_all_tabs()

        for tab_id, factory in factories.items():
            widget = factory(services, runtime)
            qtbot.addWidget(widget)
            assert widget is not None, f"Таб '{tab_id}' вернул None"

    def test_tab_factory_no_placeholders(self, qtbot):
        """TabFactory с register_all_tabs() — ни одного PlaceholderTab."""
        factories = register_all_tabs()
        factory = TabFactory(_make_app_services(), auth_ctx=None, custom_factories=factories)

        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)
        factory.create_tabs(tab_widget)

        assert tab_widget.count() == 7

        # Проверить что ни один таб не PlaceholderTab
        for i in range(tab_widget.count()):
            widget = tab_widget.widget(i)
            assert not isinstance(widget, PlaceholderTab), f"Таб {i} ({TAB_ORDER[i]['id']}) — всё ещё PlaceholderTab"

    def test_tab_factory_titles_match(self, qtbot):
        """Заголовки табов соответствуют TAB_ORDER."""
        factories = register_all_tabs()
        factory = TabFactory(_make_app_services(), auth_ctx=None, custom_factories=factories)

        tab_widget = QTabWidget()
        qtbot.addWidget(tab_widget)
        factory.create_tabs(tab_widget)

        for i, tab_info in enumerate(TAB_ORDER):
            assert tab_widget.tabText(i) == tab_info["title"]
