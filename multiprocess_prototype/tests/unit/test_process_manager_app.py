"""
Тесты ProcessManagerProcessApp — подкласс оркестратора прототипа (Task 3.2 + 1.4).

Проверяют:
  - _setup_topology_manager() вызывает configure_topology_manager
  - PROCESS_MANAGER_APP_CLASS_PATH соответствует реальному пути
  - Наследование от ProcessManagerProcess
  - _setup_state_store() создаёт StateStoreManager без router (Задача 1.4)
  - _setup_state_store() с пустым app_config → state содержит ключ system
  - shutdown() корректно завершает StateStoreManager (Задача 1.4)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_ROOT = Path(__file__).resolve().parents[3]  # Inspector_bottles/
_V3_ROOT = Path(__file__).resolve().parents[2]  # multiprocess_prototype/
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_prototype.backend.processes.process_manager.process import (
    PROCESS_MANAGER_APP_CLASS_PATH,
    ProcessManagerProcessApp,
)
from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)


class TestProcessManagerProcessApp:
    """Тесты ProcessManagerProcessApp."""

    def test_is_subclass_of_process_manager_process(self) -> None:
        """ProcessManagerProcessApp наследуется от ProcessManagerProcess."""
        assert issubclass(ProcessManagerProcessApp, ProcessManagerProcess)

    def test_class_path_matches_real_location(self) -> None:
        """PROCESS_MANAGER_APP_CLASS_PATH разрешается в реальный класс."""
        parts = PROCESS_MANAGER_APP_CLASS_PATH.rsplit(".", 1)
        module_path, class_name = parts[0], parts[1]

        import importlib
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        assert cls is ProcessManagerProcessApp

    def test_setup_topology_manager_calls_configure(self) -> None:
        """_setup_topology_manager() вызывает configure_topology_manager с TopologyManager."""
        app = object.__new__(ProcessManagerProcessApp)
        mock_tm = MagicMock()

        with patch.object(
            ProcessManagerProcess,
            "_setup_topology_manager",
            side_effect=lambda: setattr(app, "_topology_manager", mock_tm),
        ), patch(
            "multiprocess_prototype.registers.system_topology.topology_adapter.configure_topology_manager"
        ) as mock_configure:
            app._setup_topology_manager()

            mock_configure.assert_called_once_with(mock_tm)

    def test_setup_topology_manager_skips_when_none(self) -> None:
        """_setup_topology_manager() не вызывает configure если TopologyManager = None."""
        app = object.__new__(ProcessManagerProcessApp)

        with patch.object(
            ProcessManagerProcess,
            "_setup_topology_manager",
            side_effect=lambda: setattr(app, "_topology_manager", None),
        ), patch(
            "multiprocess_prototype.registers.system_topology.topology_adapter.configure_topology_manager"
        ) as mock_configure:
            app._setup_topology_manager()

            mock_configure.assert_not_called()


# ---------------------------------------------------------------------------
# Задача 1.4 — тесты _setup_state_store() и shutdown()
# ---------------------------------------------------------------------------

def _make_minimal_app(app_config: dict | None = None) -> ProcessManagerProcessApp:
    """Создать ProcessManagerProcessApp с минимальным set of атрибутов.

    Использует object.__new__ (без реального __init__ — нет IPC/multiprocessing).
    Задаёт только атрибуты, которые реально читает _setup_state_store().
    """
    app = object.__new__(ProcessManagerProcessApp)
    # Атрибуты из ProcessManagerProcess._create_components
    app._state_store_manager = None
    # router_manager=None — StateStoreManager работает без IPC
    app.router_manager = None
    # config dict — то, что читает get_config()
    app.config = {"app_config": app_config} if app_config is not None else {}
    app.config_handler = None  # get_config упадёт к self.config.get(...)
    # Логирование — _log_info вызывается в _setup_state_store()
    app._log_info = MagicMock()
    app._log_warning = MagicMock()
    return app


class TestSetupStateStoreWithoutRouter:
    """test_setup_state_store_without_router — Задача 1.4, тест 6."""

    def test_state_store_manager_created(self):
        """_setup_state_store() создаёт _state_store_manager без router."""
        app = _make_minimal_app(app_config={})
        app._setup_state_store()

        assert app._state_store_manager is not None

    def test_store_accessible(self):
        """После _setup_state_store() атрибут .store доступен на менеджере."""
        app = _make_minimal_app(app_config={})
        app._setup_state_store()

        assert hasattr(app._state_store_manager, "store")
        assert app._state_store_manager.store is not None

    def test_idempotent_guard(self):
        """Повторный вызов _setup_state_store() — не создаёт второй менеджер."""
        app = _make_minimal_app(app_config={})
        app._setup_state_store()
        first_manager = app._state_store_manager

        app._setup_state_store()  # второй вызов
        assert app._state_store_manager is first_manager


class TestSetupStateStoreWithEmptyAppConfig:
    """test_setup_state_store_with_empty_app_config — Задача 1.4, тест 7."""

    def test_initial_state_contains_system_key(self):
        """С app_config={} начальное состояние содержит ключ system."""
        app = _make_minimal_app(app_config={})
        app._setup_state_store()

        # system.status устанавливается в build_initial_state даже при пустом app_config
        status = app._state_store_manager.store.get("system.status")
        assert status == "initializing"

    def test_app_config_none_does_not_crash(self):
        """Если app_config не задан в конфиге, _setup_state_store() не падает."""
        app = _make_minimal_app(app_config=None)
        # app.config пустой → get_config("app_config") вернёт None → fallback на {}
        app._setup_state_store()

        assert app._state_store_manager is not None
        status = app._state_store_manager.store.get("system.status")
        assert status == "initializing"

    def test_middleware_registered(self):
        """После _setup_state_store() pipeline содержит validation и throttle middleware."""
        app = _make_minimal_app(app_config={})
        app._setup_state_store()

        pipeline = app._state_store_manager.pipeline
        assert not pipeline.is_empty


class TestShutdownClearsStateStore:
    """test_shutdown_clears_state_store — Задача 1.4, тест 8."""

    def test_shutdown_calls_state_store_shutdown(self):
        """shutdown() вызывает _state_store_manager.shutdown()."""
        app = _make_minimal_app(app_config={})
        app._setup_state_store()

        mock_ssm = MagicMock()
        app._state_store_manager = mock_ssm

        # Перехватываем super().shutdown() чтобы не запускать реальный lifecycle
        with patch.object(ProcessManagerProcess, "shutdown", return_value=True):
            app.shutdown()

        mock_ssm.shutdown.assert_called_once()

    def test_shutdown_without_state_store_does_not_crash(self):
        """shutdown() не падает если _state_store_manager = None."""
        app = _make_minimal_app()
        app._state_store_manager = None

        with patch.object(ProcessManagerProcess, "shutdown", return_value=True):
            result = app.shutdown()

        assert result is True

    def test_double_shutdown_does_not_crash(self):
        """Двойной вызов shutdown() не поднимает исключений."""
        app = _make_minimal_app(app_config={})
        app._setup_state_store()

        with patch.object(ProcessManagerProcess, "shutdown", return_value=True):
            app.shutdown()
            app.shutdown()  # второй вызов — не должен падать
