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
_TOPOLOGY_PATH = Path(__file__).resolve().parents[2] / "topology" / "inspection_basic.yaml"
_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


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
        from multiprocess_prototype.registers.manager import RegistersManagerV2
        from multiprocess_prototype.frontend.app_context import build_app_context
        from multiprocess_prototype.frontend.topology_holder import TopologyHolder
        from multiprocess_prototype.frontend.startup_checks import StartupChecker
        from multiprocess_prototype.registers.connection_map import ConnectionMap
        from multiprocess_prototype.frontend.bridge.command_catalog import CommandCatalog
        from multiprocess_prototype.frontend.bridge.command_validator import CommandValidator
        from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge
        from multiprocess_prototype.frontend.actions.bus_factory import create_action_bus
        from multiprocess_prototype.frontend.windows.main_window import MainWindow
        from multiprocess_prototype.frontend.tab_factory import TabFactory
        from multiprocess_prototype.frontend.widgets.tabs import register_all_tabs

        # 1. Plugin discovery — реальный, проверяем интеграцию
        PluginRegistry.discover(str(_PLUGINS_DIR))
        registered = PluginRegistry.list()
        assert len(registered) >= 19, f"Ожидалось >=19 плагинов, получено {len(registered)}"

        # 2. RegistersManager — из реального реестра плагинов
        rm = RegistersManagerV2.from_registry(PluginRegistry)
        assert rm is not None, "RegistersManagerV2 создан"

        # 3. AppContext — DI-контейнер
        ctx = build_app_context(
            mock_process,
            plugin_registry=PluginRegistry,
            registers_manager=rm,
        )
        assert ctx is not None, "AppContext создан"
        assert ctx.command_sender is not None, "CommandSender инициализирован"

        # 4. TopologyHolder — контейнер с уведомлениями
        holder = TopologyHolder(topology_dict)
        ctx.extras["topology_holder"] = holder
        ctx.extras["topology"] = topology_dict
        assert holder.topology is not None, "TopologyHolder содержит topology"

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
            topology_holder=holder,
        )
        ctx.extras["topology_bridge"] = bridge
        assert bridge is not None, "TopologyBridge создан"

        # 9. ActionBus — undo/redo шина
        action_bus = create_action_bus(rm, holder, topology_bridge=bridge)
        ctx.extras["action_bus"] = action_bus
        assert action_bus is not None, "ActionBus создан"
        assert action_bus.can_undo() is False, "ActionBus пуст — undo недоступен"

        # 10. MainWindow + TabFactory — создание окна и всех табов
        window = MainWindow()
        qtbot.addWidget(window)
        window.set_action_bus(action_bus)

        factories = register_all_tabs()
        assert len(factories) >= 7, f"Зарегистрировано >=7 tab factories: {len(factories)}"

        tab_factory = TabFactory(ctx, custom_factories=factories)
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

    def test_topology_holder_callback(self, topology_dict):
        """TopologyHolder вызывает callback при изменении."""
        from multiprocess_prototype.frontend.topology_holder import TopologyHolder

        holder = TopologyHolder(topology_dict)
        callback = MagicMock()
        holder.on_changed(callback)

        new_topo = {**topology_dict, "name": "modified"}
        holder.set_topology(new_topo)
        callback.assert_called_once()
