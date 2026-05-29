"""Integration smoke test — воспроизводит реальный bootstrap из app.py.

Проверяет что вся инициализация проходит без ошибок:
AppContext -> RegistersManager -> TopologyBridge -> ActionBus -> TabFactory -> 7 табов.
"""

from __future__ import annotations

import pytest
import yaml
from pathlib import Path
from unittest.mock import MagicMock

# Путь к реальной topology
_TOPOLOGY_PATH = Path(__file__).resolve().parents[2] / "backend" / "topology" / "inspection_basic.yaml"
_PLUGINS_DIR = Path(__file__).resolve().parents[3] / "Plugins"


@pytest.fixture
def topology_dict():
    """Загрузить реальную topology."""
    return yaml.safe_load(_TOPOLOGY_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def mock_process():
    """Mock GuiProcess с минимальным API для build_app_context + CommandSender."""
    process = MagicMock()
    process.name = "gui_test"
    # build_app_context обращается к process._bridge
    process._bridge = MagicMock()
    process._bridge.set_state_callback = MagicMock()
    # CommandSender использует process.send_message
    process.send_message = MagicMock()
    # Логирование (используется в app.py при startup errors)
    process._log_info = MagicMock()
    process._log_warning = MagicMock()
    process._log_error = MagicMock()
    process._record_metric = MagicMock()
    process.router_manager = MagicMock()
    return process


class TestPhase15Smoke:
    """E2E smoke test: полный bootstrap цикл."""

    def test_full_bootstrap(self, qtbot, mock_process, topology_dict):
        """Воспроизвести полный bootstrap из app.py."""
        from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
        from multiprocess_framework.modules.registers_module import RegistersManager
        from multiprocess_prototype.frontend.app_context import build_app_context
        from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryStore
        from multiprocess_prototype.frontend.qt_event_bus import QtEventBus
        from multiprocess_prototype.frontend.startup_checks import StartupChecker
        from multiprocess_prototype.registers.connection_map import ConnectionMap
        from multiprocess_prototype.frontend.bridge import (
            CommandCatalog,
            CommandValidator,
            TopologyBridge,
        )
        from multiprocess_prototype.frontend.actions.bus_factory import create_action_bus
        from multiprocess_prototype.frontend.windows.main_window import MainWindow
        from multiprocess_prototype.frontend.tab_factory import TabFactory
        from multiprocess_prototype.frontend.widgets.tabs import register_all_tabs

        # 1. Plugin discovery — реальный, проверяем интеграцию
        PluginRegistry.discover(str(_PLUGINS_DIR))
        registered = PluginRegistry.list()
        assert len(registered) >= 19, f"Ожидалось >=19 плагинов, получено {len(registered)}"

        # 2. RegistersManager — из реального реестра плагинов
        rm = RegistersManager.from_registry(PluginRegistry)
        assert rm is not None, "RegistersManager создан"

        # 3. AppContext — DI-контейнер
        ctx = build_app_context(
            mock_process,
            plugin_registry=PluginRegistry,
            registers_manager=rm,
        )
        assert ctx is not None, "AppContext создан"
        assert ctx.command_sender is not None, "CommandSender инициализирован"

        # 4. EventBus + TopologyRepositoryStore (G.3): store владеет topology dict
        # и публикует TopologyReplaced (как в app.py composition root).
        event_bus = QtEventBus()
        topology_store = TopologyRepositoryStore(topology_dict, events=event_bus)
        ctx.extras["event_bus"] = event_bus
        ctx.extras["topology_store"] = topology_store
        assert topology_store.topology is not None, "TopologyRepositoryStore содержит topology"

        # 5. StartupChecker — валидация topology + плагинов
        checker = StartupChecker()
        report = checker.check_all(topology_dict, registry=PluginRegistry)
        assert report.ok, f"Startup validation не прошла: {report.errors}"

        # 6. ConnectionMap + CommandCatalog — маршрутизация команд
        cmap = ConnectionMap.from_topology(topology_dict)
        catalog = CommandCatalog.from_registry_and_map(PluginRegistry, cmap)
        assert len(catalog) > 0, "CommandCatalog содержит команды"

        # 7. CommandValidator — проверка команд перед отправкой
        validator = CommandValidator(catalog, rm)
        assert validator is not None, "CommandValidator создан"

        # 8. TopologyBridge — мост GUI <-> Runtime
        bridge = TopologyBridge(
            command_sender=ctx.command_sender,
            command_catalog=catalog,
            command_validator=validator,
            registers_manager=rm,
            topology_holder=topology_store,
        )
        ctx.extras["topology_bridge"] = bridge
        assert bridge is not None, "TopologyBridge создан"

        # 9. ActionBus — undo/redo шина
        action_bus = create_action_bus(rm, topology_store, topology_bridge=bridge)
        ctx.extras["action_bus"] = action_bus
        assert action_bus is not None, "ActionBus создан"
        assert action_bus.can_undo() is False, "ActionBus пуст — undo недоступен"

        # 10. MainWindow + TabFactory — создание окна и всех табов
        # Табы ленивые (LazyTabWidget) — create(services, runtime) вызывается только
        # на showEvent, который в headless-тесте не наступает. Поэтому app_services
        # здесь не разыменовывается; полный bootstrap проверяют per-tab create-тесты.
        window = MainWindow()
        qtbot.addWidget(window)
        # G.4.4: set_undo_controller принимает UndoRedoController; legacy ActionBus
        # удовлетворяет ему структурно (в production сюда идёт services.commands).
        window.set_undo_controller(action_bus)

        factories = register_all_tabs()
        assert len(factories) >= 7, f"Зарегистрировано >=7 tab factories: {len(factories)}"

        # G.5.2: TabFactory принимает explicit (app_services, auth_ctx, runtime).
        # Табы ленивые → app_services не разыменовывается в headless-тесте.
        tab_factory = TabFactory(
            ctx.app_services,
            auth_ctx=ctx.auth,
            custom_factories=factories,
        )
        tab_factory.create_tabs(window.tab_widget)

        # 11. Проверить что все 7 табов созданы
        tab_count = window.tab_widget.count()
        assert tab_count >= 7, f"Ожидалось >=7 табов, получено {tab_count}"

        # 12. ErrorBanner существует
        assert hasattr(window, "_error_banner"), "MainWindow имеет ErrorBanner"

    def test_startup_validation_with_real_topology(self, topology_dict):
        """StartupChecker на реальной topology — нет ошибок."""
        from multiprocess_prototype.frontend.startup_checks import StartupChecker

        checker = StartupChecker()
        report = checker.check_all(topology_dict)
        assert report.ok, f"Ошибки: {report.errors}"
        assert len(report.errors) == 0

    def test_topology_store_publishes_on_change(self, topology_dict):
        """TopologyRepositoryStore публикует TopologyReplaced при set_topology (G.3)."""
        from multiprocess_prototype.adapters.stores.topology_repository import TopologyRepositoryStore
        from multiprocess_prototype.domain.events import TopologyReplaced
        from multiprocess_prototype.domain.tests._fakes import FakeEventBus

        events = FakeEventBus()
        store = TopologyRepositoryStore(topology_dict, events=events)

        new_topo = {**topology_dict, "name": "modified"}
        store.set_topology(new_topo)

        assert store.topology == new_topo
        assert len(events.published) == 1
        assert isinstance(events.published[0], TopologyReplaced)
