"""Тесты PluginOrchestrator — lifecycle-оркестрация плагинов через IProcessServices.

Проверяет:
- Загрузку плагина по dotted path
- Обработку невалидного пути
- load_and_configure_managers
- boot(): IDLE → READY → RUNNING
- shutdown(): в обратном порядке
- .plugins property
- registers_manager == None без schemas
- Пустой plugin_defs → нет плагинов
"""

import pytest

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    PluginState,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import PluginOrchestrator


# ---------------------------------------------------------------------------
# Тестовые плагины (определены здесь, чтобы их можно было загрузить по dotted path)
# ---------------------------------------------------------------------------


class SimplePlugin(ProcessModulePlugin):
    """Простой плагин для тестов: отслеживает вызовы lifecycle-методов."""

    name = "simple"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None:
        self._configured = True

    def start(self, ctx: PluginContext) -> None:
        self._started = True

    def shutdown(self, ctx: PluginContext) -> None:
        self._shutdown = True

    def process(self, items):
        return items


class AlphaPlugin(ProcessModulePlugin):
    """Первый плагин в порядке загрузки — для проверки обратного порядка shutdown."""

    name = "alpha"
    category = "processing"
    shutdown_order: list = []

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def shutdown(self, ctx: PluginContext) -> None:
        AlphaPlugin.shutdown_order.append("alpha")


class BetaPlugin(ProcessModulePlugin):
    """Второй плагин — для проверки обратного порядка shutdown."""

    name = "beta"
    category = "processing"

    def configure(self, ctx: PluginContext) -> None: ...

    def start(self, ctx: PluginContext) -> None: ...

    def shutdown(self, ctx: PluginContext) -> None:
        AlphaPlugin.shutdown_order.append("beta")


# ---------------------------------------------------------------------------
# Dotted paths для тестовых плагинов
# ---------------------------------------------------------------------------

_MODULE = "multiprocess_framework.modules.process_module.tests.test_plugin_orchestrator"
_SIMPLE_PATH = f"{_MODULE}.SimplePlugin"
_ALPHA_PATH = f"{_MODULE}.AlphaPlugin"
_BETA_PATH = f"{_MODULE}.BetaPlugin"


# ---------------------------------------------------------------------------
# _load_plugin
# ---------------------------------------------------------------------------


def test_load_plugin_by_path():
    """_load_plugin загружает класс по dotted path и возвращает экземпляр."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    plugin = orch._load_plugin(_SIMPLE_PATH, "simple_test")
    assert isinstance(plugin, SimplePlugin)


def test_load_plugin_invalid_path():
    """_load_plugin бросает исключение при невалидном dotted path."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    with pytest.raises(Exception):
        orch._load_plugin("nonexistent.module.FakePlugin", "fake")


def test_load_plugin_not_plugin_subclass():
    """_load_plugin бросает TypeError если класс не является ProcessModulePlugin."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    # object не является ProcessModulePlugin
    with pytest.raises(TypeError):
        orch._load_plugin("builtins.dict", "bad_class")


# ---------------------------------------------------------------------------
# load_and_configure_managers
# ---------------------------------------------------------------------------


def test_load_and_configure_managers_loads_plugins():
    """load_and_configure_managers загружает плагины в _early_plugins."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    plugin_defs = [{"plugin_class": _SIMPLE_PATH, "plugin_name": "simple_test"}]
    orch.load_and_configure_managers(plugin_defs)
    assert len(orch._early_plugins) == 1
    plugin, _ctx = orch._early_plugins[0]
    assert isinstance(plugin, SimplePlugin)


def test_empty_plugin_defs():
    """load_and_configure_managers с пустым списком — _early_plugins пуст."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers([])
    assert orch._early_plugins == []


def test_load_and_configure_managers_sets_plugin_name():
    """plugin_name из defs присваивается плагину если у него нет своего имени."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    # SimplePlugin уже имеет name="simple", поэтому имя не перезаписывается
    plugin_defs = [{"plugin_class": _SIMPLE_PATH, "plugin_name": "custom_name"}]
    orch.load_and_configure_managers(plugin_defs)
    plugin, _ = orch._early_plugins[0]
    # Если у класса есть name — оркестратор не перезаписывает
    assert plugin.name == "simple"


# ---------------------------------------------------------------------------
# boot() — lifecycle IDLE → READY → RUNNING
# ---------------------------------------------------------------------------


def test_boot_lifecycle():
    """boot() проводит плагины IDLE → READY → RUNNING."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    plugin_defs = [{"plugin_class": _SIMPLE_PATH, "plugin_name": "simple_test"}]
    orch.load_and_configure_managers(plugin_defs)
    orch.boot()

    assert len(orch.plugins) == 1
    plugin = orch.plugins[0]
    assert plugin.state == PluginState.RUNNING


def test_boot_calls_configure_and_start():
    """После boot() плагин имеет атрибуты _configured и _started."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    plugin_defs = [{"plugin_class": _SIMPLE_PATH, "plugin_name": "simple_test"}]
    orch.load_and_configure_managers(plugin_defs)
    orch.boot()

    plugin = orch.plugins[0]
    assert getattr(plugin, "_configured", False) is True
    assert getattr(plugin, "_started", False) is True


def test_boot_no_plugins_logs_info():
    """boot() без плагинов записывает info-сообщение (нет плагинов)."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    orch.load_and_configure_managers([])
    orch.boot()

    assert orch.plugins == []
    assert any("нет плагинов" in e["msg"] for e in services.logs)


# ---------------------------------------------------------------------------
# shutdown() — в обратном порядке
# ---------------------------------------------------------------------------


def test_shutdown_reverse_order():
    """shutdown() вызывается в обратном порядке относительно boot()."""
    # Сбросить глобальный список
    AlphaPlugin.shutdown_order = []

    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    plugin_defs = [
        {"plugin_class": _ALPHA_PATH, "plugin_name": "alpha"},
        {"plugin_class": _BETA_PATH, "plugin_name": "beta"},
    ]
    orch.load_and_configure_managers(plugin_defs)
    orch.boot()
    orch.shutdown()

    # beta должна завершиться раньше alpha (обратный порядок)
    assert AlphaPlugin.shutdown_order == ["beta", "alpha"]


def test_shutdown_sets_stopped_state():
    """После shutdown() плагины находятся в состоянии STOPPED."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    plugin_defs = [{"plugin_class": _SIMPLE_PATH, "plugin_name": "simple_test"}]
    orch.load_and_configure_managers(plugin_defs)
    orch.boot()
    orch.shutdown()

    for plugin in orch.plugins:
        assert plugin.state == PluginState.STOPPED


# ---------------------------------------------------------------------------
# .plugins property
# ---------------------------------------------------------------------------


def test_plugins_property_returns_loaded_plugins():
    """.plugins возвращает загруженные плагины после boot()."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    plugin_defs = [{"plugin_class": _SIMPLE_PATH, "plugin_name": "simple_test"}]
    orch.load_and_configure_managers(plugin_defs)
    orch.boot()

    plugins = orch.plugins
    assert len(plugins) == 1
    assert isinstance(plugins[0], SimplePlugin)


def test_plugins_property_empty_before_boot():
    """.plugins пуст до boot()."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    assert orch.plugins == []


# ---------------------------------------------------------------------------
# registers_manager
# ---------------------------------------------------------------------------


def test_registers_manager_none_without_schemas():
    """registers_manager == None если плагины без register schema."""
    services = MockProcessServices(name="test")
    orch = PluginOrchestrator(services=services)
    plugin_defs = [{"plugin_class": _SIMPLE_PATH, "plugin_name": "simple_test"}]
    orch.load_and_configure_managers(plugin_defs)
    orch.boot()

    # SimplePlugin не имеет register_schema — registers_manager должен быть None
    assert orch.registers_manager is None
