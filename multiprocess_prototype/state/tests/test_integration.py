"""test_integration.py -- Интеграционные тесты Task 8.3: StateStore в bootstrap.

Все тесты используют mock/InMemoryRouter, без реальных процессов.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from multiprocess_framework.modules.state_store_module.testing.in_memory_router import (
    InMemoryRouter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def router():
    """InMemoryRouter для тестов."""
    return InMemoryRouter()


@pytest.fixture
def initial_state():
    """Пример initial_state от build_initial_state."""
    return {
        "processes": {
            "camera_0": {
                "config": {"plugins": [], "chain_targets": [], "priority": "high"},
                "state": {
                    "status": "stopped",
                    "pid": None,
                    "fps": 0.0,
                    "frame_count": 0,
                    "error": None,
                },
            },
            "processor": {
                "config": {"plugins": [], "chain_targets": [], "priority": "normal"},
                "state": {
                    "status": "stopped",
                    "pid": None,
                    "fps": 0.0,
                    "frame_count": 0,
                    "error": None,
                },
            },
        },
        "system": {"stop_timeout": 5.0, "shm_budget_mb": 512, "log_dir": ""},
        "wires": {},
    }


@pytest.fixture
def throttle_rules():
    """Throttle-правила для тестов."""
    from multiprocess_prototype.state.manager_setup import build_throttle_rules

    return build_throttle_rules()


# ---------------------------------------------------------------------------
# ProcessManagerProcessApp — тесты StateStoreManager
# ---------------------------------------------------------------------------


def _make_pm_app(router, initial_state, throttle_rules):
    """Создать ProcessManagerProcessApp с минимальными mock-зависимостями.

    Не вызывает initialize() — только __init__ + ручной вызов _setup_state_store().
    """
    from multiprocess_prototype.orchestrator import ProcessManagerProcessApp

    # Минимальный shared_resources mock
    shared = MagicMock()
    shared.get_process_data.return_value = MagicMock(custom={})

    pm = ProcessManagerProcessApp.__new__(ProcessManagerProcessApp)
    # Ручная установка полей вместо __init__ (обходим multiprocessing)
    pm.name = "ProcessManager"
    pm.config = {
        "initial_state": initial_state,
        "state_throttle_rules": throttle_rules,
    }
    pm.config_handler = None
    pm.router_manager = router
    pm.command_manager = MagicMock()
    pm._state_store_manager = None

    return pm


class TestProcessManagerProcessApp:
    """Тесты для ProcessManagerProcessApp._setup_state_store()."""

    def test_creates_state_store(self, router, initial_state, throttle_rules):
        """ProcessManagerProcessApp создаёт StateStoreManager."""
        pm = _make_pm_app(router, initial_state, throttle_rules)
        pm._setup_state_store()

        assert pm._state_store_manager is not None
        assert pm._state_store_manager.is_initialized

    def test_state_store_has_initial_state(self, router, initial_state, throttle_rules):
        """Initial_state прокинут в TreeStore."""
        pm = _make_pm_app(router, initial_state, throttle_rules)
        pm._setup_state_store()

        # Проверяем доступ к initial state через store
        value = pm._state_store_manager.store.get("processes.camera_0.state.status")
        assert value == "stopped"

    def test_middleware_attached(self, router, initial_state, throttle_rules):
        """ThrottleMiddleware подключен к pipeline."""
        pm = _make_pm_app(router, initial_state, throttle_rules)
        pm._setup_state_store()

        pipeline = pm._state_store_manager.pipeline
        # Pipeline содержит хотя бы один middleware
        assert len(pipeline._middlewares) > 0
        assert pipeline._middlewares[0].name == "throttle"

    def test_no_middleware_without_rules(self, router, initial_state):
        """Без throttle_rules middleware не подключается."""
        pm = _make_pm_app(router, initial_state, throttle_rules=None)
        pm.config["state_throttle_rules"] = None
        pm._setup_state_store()

        pipeline = pm._state_store_manager.pipeline
        assert len(pipeline._middlewares) == 0

    def test_commands_registered(self, router, initial_state, throttle_rules):
        """state.set/get/subscribe зарегистрированы в CommandManager."""
        pm = _make_pm_app(router, initial_state, throttle_rules)
        pm._setup_state_store()

        # register_commands вызывает command_manager.register_command N раз
        assert pm.command_manager.register_command.called
        registered_names = [call.args[0] for call in pm.command_manager.register_command.call_args_list]
        assert "state.set" in registered_names
        assert "state.get" in registered_names
        assert "state.subscribe" in registered_names


# ---------------------------------------------------------------------------
# GenericProcessApp — тесты StateProxy
# ---------------------------------------------------------------------------


def _make_generic_app(router):
    """Создать GenericProcessApp с минимальными mock-зависимостями.

    Не вызывает полный lifecycle — только тестирует _init_custom_managers().
    """
    from multiprocess_prototype.generic_process_app import GenericProcessApp

    gp = GenericProcessApp.__new__(GenericProcessApp)
    gp.name = "test_process"
    gp.config = {"config": {"plugins": []}}
    gp.config_handler = None
    gp.router_manager = router
    gp.command_manager = MagicMock()
    gp.worker_manager = None
    gp.memory_manager = None
    gp.shared_resources = None
    gp.logger_manager = None
    gp._state_proxy = None

    return gp


class TestGenericProcessApp:
    """Тесты для GenericProcessApp._init_custom_managers()."""

    def test_creates_state_proxy(self, router):
        """GenericProcessApp создаёт StateProxy."""
        gp = _make_generic_app(router)
        gp._init_custom_managers()

        assert gp._state_proxy is not None
        assert gp._state_proxy.is_initialized
        assert gp._state_proxy.process_name == "test_process"

    def test_state_changed_handler_registered(self, router):
        """Handler state.changed зарегистрирован в router."""
        gp = _make_generic_app(router)
        gp._init_custom_managers()

        # InMemoryRouter должен содержать handler для state.changed
        assert "state.changed" in router._handlers

    def test_shutdown_cleans_proxy(self, router):
        """shutdown() вызывает StateProxy.shutdown()."""
        gp = _make_generic_app(router)
        gp._init_custom_managers()

        # Mock плагинов для shutdown (GenericProcess.shutdown ожидает их)
        gp._plugins = []
        gp._plugin_contexts = []

        # Запоминаем proxy для проверки
        proxy = gp._state_proxy

        # Mock super().shutdown() чтобы не лезть в ProcessModule
        with patch.object(type(gp).__mro__[2], "shutdown", return_value=True):
            gp.shutdown()

        assert not proxy.is_initialized


# ---------------------------------------------------------------------------
# bootstrap — тесты интеграции main.py
# ---------------------------------------------------------------------------


class TestBootstrapIntegration:
    """Тесты bootstrap параметров в main.py."""

    def test_bootstrap_builds_launcher_with_orchestrator(self, tmp_path):
        """bootstrap() создаёт SystemLauncher с правильным orchestrator_class_path."""
        import yaml

        # Минимальный topology
        topology = {
            "name": "test",
            "description": "test topology",
            "processes": [
                {
                    "process_name": "gui",
                    "process_class": "multiprocess_prototype.frontend.process.GuiProcess",
                    "plugins": [],
                }
            ],
        }
        bp_path = tmp_path / "test.yaml"
        bp_path.write_text(yaml.dump(topology), encoding="utf-8")

        # Минимальный system.yaml
        sys_yaml = {
            "system": {"stop_timeout": 3.0, "shm_budget_mb": 256, "log_dir": ""},
        }
        sys_path = tmp_path / "system.yaml"
        sys_path.write_text(yaml.dump(sys_yaml), encoding="utf-8")

        # Патчим CONFIG_PATH и DEFAULT_BLUEPRINT
        with (
            patch("multiprocess_prototype.main.CONFIG_PATH", sys_path),
            patch("multiprocess_prototype.main.DEFAULT_BLUEPRINT", bp_path),
        ):
            from multiprocess_prototype.main import bootstrap

            launcher = bootstrap(str(bp_path))

        assert launcher._orchestrator_class_path == ("multiprocess_prototype.orchestrator.ProcessManagerProcessApp")
        assert "initial_state" in launcher._orchestrator_config
        assert "state_throttle_rules" in launcher._orchestrator_config

    def test_initial_state_has_processes(self, tmp_path):
        """initial_state в orchestrator_config содержит процессы из topology."""
        import yaml

        topology = {
            "name": "test",
            "description": "test",
            "processes": [
                {
                    "process_name": "camera_0",
                    "plugins": [],
                    "chain_targets": ["gui"],
                    "priority": "high",
                },
                {
                    "process_name": "gui",
                    "process_class": "multiprocess_prototype.frontend.process.GuiProcess",
                    "plugins": [],
                },
            ],
        }
        bp_path = tmp_path / "test.yaml"
        bp_path.write_text(yaml.dump(topology), encoding="utf-8")

        sys_yaml = {
            "system": {"stop_timeout": 3.0, "shm_budget_mb": 256, "log_dir": ""},
        }
        sys_path = tmp_path / "system.yaml"
        sys_path.write_text(yaml.dump(sys_yaml), encoding="utf-8")

        with (
            patch("multiprocess_prototype.main.CONFIG_PATH", sys_path),
            patch("multiprocess_prototype.main.DEFAULT_BLUEPRINT", bp_path),
        ):
            from multiprocess_prototype.main import bootstrap

            launcher = bootstrap(str(bp_path))

        state = launcher._orchestrator_config["initial_state"]
        assert "camera_0" in state["processes"]
        assert state["processes"]["camera_0"]["state"]["status"] == "stopped"


# ---------------------------------------------------------------------------
# PluginContext — StateProxy доступен плагинам
# ---------------------------------------------------------------------------


class TestPluginContextStateProxy:
    """Тест: плагин получает ctx.state_proxy != None."""

    def test_plugin_context_gets_state_proxy(self, router):
        """PluginContext.state_proxy заполнен после _init_custom_managers."""
        gp = _make_generic_app(router)

        # Добавим минимальный плагин в config чтобы проверить ctx
        gp.config = {
            "config": {
                "plugins": [],  # Пустой список — base_ctx всё равно создаётся
            }
        }
        gp._init_custom_managers()

        # Проверяем что state_proxy установлен
        assert gp._state_proxy is not None

        # Проверяем что PluginContext получает proxy через services (Phase 2.2 API)
        from multiprocess_framework.modules.process_module.plugins.base import (
            PluginContext,
        )
        from multiprocess_framework.modules.process_module.plugins.testing import (
            MockProcessServices,
        )

        services = MockProcessServices(
            name="test_process",
            state_proxy=gp._state_proxy,
        )
        ctx = PluginContext(services=services, config={})

        assert ctx.state_proxy is not None
        assert ctx.state_proxy is gp._state_proxy


# ---------------------------------------------------------------------------
# manager_setup — тесты throttle_rules
# ---------------------------------------------------------------------------


class TestManagerSetup:
    """Тесты для build_throttle_rules."""

    def test_build_throttle_rules_returns_dict(self):
        """build_throttle_rules возвращает непустой dict."""
        from multiprocess_prototype.state.manager_setup import build_throttle_rules

        rules = build_throttle_rules()
        assert isinstance(rules, dict)
        assert len(rules) > 0

    def test_throttle_rules_have_expected_keys(self):
        """Правила содержат паттерны для fps, frame_count, drops."""
        from multiprocess_prototype.state.manager_setup import build_throttle_rules

        rules = build_throttle_rules()
        keys = list(rules.keys())
        assert any("fps" in k for k in keys)
        assert any("frame_count" in k for k in keys)
        assert any("drops" in k for k in keys)
