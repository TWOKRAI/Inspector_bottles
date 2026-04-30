"""
Тесты соответствия контрактам interfaces.py.

Проверяют, что реализации соответствуют своим интерфейсам.
"""

import pytest

from ..interfaces import ISystemLauncher, IProcessManagerProcess, IProcessRegistry
from ..launcher.system_launcher import SystemLauncher
from ..core.process_registry import ProcessRegistry


class TestISystemLauncherContract:
    """SystemLauncher реализует ISystemLauncher."""

    def test_system_launcher_has_add_process(self) -> None:
        launcher = SystemLauncher()
        assert hasattr(launcher, "add_process")
        assert callable(launcher.add_process)

    def test_system_launcher_has_run(self) -> None:
        launcher = SystemLauncher()
        assert hasattr(launcher, "run")
        assert callable(launcher.run)

    def test_system_launcher_has_start(self) -> None:
        launcher = SystemLauncher()
        assert hasattr(launcher, "start")
        assert callable(launcher.start)

    def test_system_launcher_has_stop(self) -> None:
        launcher = SystemLauncher()
        assert hasattr(launcher, "stop")
        assert callable(launcher.stop)

    def test_system_launcher_has_shutdown(self) -> None:
        launcher = SystemLauncher()
        assert hasattr(launcher, "shutdown")
        assert callable(launcher.shutdown)

    def test_system_launcher_has_wait(self) -> None:
        launcher = SystemLauncher()
        assert hasattr(launcher, "wait")
        assert callable(launcher.wait)

    def test_system_launcher_has_get_status(self) -> None:
        launcher = SystemLauncher()
        assert hasattr(launcher, "get_status")
        assert callable(launcher.get_status)

    def test_system_launcher_has_get_stats(self) -> None:
        launcher = SystemLauncher()
        assert hasattr(launcher, "get_stats")
        assert callable(launcher.get_stats)

    def test_get_status_returns_dict(self) -> None:
        launcher = SystemLauncher()
        result = launcher.get_status()
        assert isinstance(result, dict)

    def test_get_stats_returns_dict(self) -> None:
        launcher = SystemLauncher()
        result = launcher.get_stats()
        assert isinstance(result, dict)

    def test_add_process_returns_self(self) -> None:
        launcher = SystemLauncher()
        result = launcher.add_process("p1", {"class": "test.P1"})
        assert result is launcher

    def test_stop_without_spawner_does_not_raise(self) -> None:
        launcher = SystemLauncher()
        launcher.stop()

    def test_shutdown_without_spawner_does_not_raise(self) -> None:
        launcher = SystemLauncher()
        launcher.shutdown()

    def test_wait_without_spawner_does_not_raise(self) -> None:
        launcher = SystemLauncher()
        launcher.wait()


class TestIProcessRegistryContract:
    """ProcessRegistry реализует IProcessRegistry."""

    def _make_registry(self) -> ProcessRegistry:
        return ProcessRegistry(logger=None)

    def test_has_add_process(self) -> None:
        registry = self._make_registry()
        assert hasattr(registry, "add_process")
        assert callable(registry.add_process)

    def test_has_get_process_by_name(self) -> None:
        registry = self._make_registry()
        assert hasattr(registry, "get_process_by_name")
        assert callable(registry.get_process_by_name)

    def test_has_create_and_register(self) -> None:
        registry = self._make_registry()
        assert hasattr(registry, "create_and_register")
        assert callable(registry.create_and_register)

    def test_has_start_all(self) -> None:
        registry = self._make_registry()
        assert hasattr(registry, "start_all")
        assert callable(registry.start_all)

    def test_has_stop_all(self) -> None:
        registry = self._make_registry()
        assert hasattr(registry, "stop_all")
        assert callable(registry.stop_all)

    def test_get_process_by_name_returns_none_for_unknown(self) -> None:
        registry = self._make_registry()
        result = registry.get_process_by_name("nonexistent")
        assert result is None

    def test_stop_all_accepts_timeout_kwarg(self) -> None:
        registry = self._make_registry()
        registry.stop_all(timeout=0.1)

    def test_has_stop_one(self) -> None:
        registry = self._make_registry()
        assert hasattr(registry, "stop_one")
        assert callable(registry.stop_one)

    def test_has_remove_process(self) -> None:
        registry = self._make_registry()
        assert hasattr(registry, "remove_process")
        assert callable(registry.remove_process)


class TestInterfaceAbstractness:
    """Интерфейсы нельзя инстанцировать напрямую."""

    def test_isystemlauncher_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            ISystemLauncher()  # type: ignore

    def test_iprocessmanagerprocess_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            IProcessManagerProcess()  # type: ignore

    def test_iprocessregistry_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            IProcessRegistry()  # type: ignore
