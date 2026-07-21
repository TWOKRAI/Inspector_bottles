# -*- coding: utf-8 -*-
"""Тесты teardown вкладки Displays (bug-hunt A-6).

DisplaysTab — дочерний виджет QTabWidget (register_all_tabs -> addTab), а не
top-level окно. Qt доставляет closeEvent только top-level виджетам либо тем,
что явно получили close() — обычный путь смерти вкладки внутри QTabWidget
(deleteLater / разрушение родителя MainWindow) closeEvent НЕ порождает.
До фикса PreviewWindowManager.close_all() в этом пути был недостижим (окна
превью и EventBus-подписка presenter'а переживали вкладку).

Покрытие:
  - close() -> closeEvent -> teardown (штатный Qt-путь, если доставлен);
  - deleteLater() (без close()) -> сигнал destroyed -> teardown — тот же
    приём, что PipelineTab (см. pipeline/tests/test_teardown.py).

Refs: docs/audits/2026-07-20_bug-hunt.md §5 A-6
"""

from __future__ import annotations

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab

from ._helpers import make_displays_services


def _make_services_with_real_bus() -> tuple[AppServices, EventBus]:
    """AppServices с реальным EventBus (нужен для проверки unsubscribe)."""
    svc = make_displays_services()
    bus = EventBus()
    svc_with_bus = AppServices(
        plugins=svc.plugins,
        services=svc.services,
        displays=svc.displays,
        recipes=svc.recipes,
        registers=svc.registers,
        topology=svc.topology,
        commands=svc.commands,
        events=bus,
        auth=svc.auth,
        config=svc.config,
    )
    return svc_with_bus, bus


class TestDisplaysTabTeardown:
    """Teardown вкладки: оба пути уничтожения снимают подписку RecipeActivated."""

    def test_close_event_triggers_teardown(self, qtbot):
        """close() -> closeEvent -> teardown (штатный Qt-путь)."""
        services, bus = _make_services_with_real_bus()
        tab = DisplaysTab.create(services)
        qtbot.addWidget(tab)
        assert tab._presenter._recipe_sub is not None

        tab.close()

        assert tab._presenter._recipe_sub is None

    def test_destroyed_signal_triggers_teardown(self, qtbot):
        """deleteLater (без close()) -> сигнал destroyed -> teardown.

        Именно так вкладка умирает внутри QTabWidget при разрушении родителя —
        closeEvent при этом не приходит (недочерний top-level виджет).
        """
        services, bus = _make_services_with_real_bus()
        tab = DisplaysTab.create(services)
        presenter = tab._presenter
        assert presenter._recipe_sub is not None

        tab.deleteLater()

        qtbot.waitUntil(lambda: presenter._recipe_sub is None, timeout=2000)

    def test_destroyed_teardown_closes_preview_windows(self, qtbot):
        """deleteLater -> teardown -> PreviewWindowManager.close_all() вызван.

        До фикса A-6 окна превью переживали вкладку (closeEvent недостижим
        для дочернего виджета QTabWidget).
        """
        from unittest.mock import MagicMock

        services, bus = _make_services_with_real_bus()
        tab = DisplaysTab.create(services)
        window = MagicMock()
        window.isVisible.return_value = True
        tab._window_manager.register("display_1", window)

        tab.deleteLater()

        qtbot.waitUntil(lambda: window.close.called, timeout=2000)
