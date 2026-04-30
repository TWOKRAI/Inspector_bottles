"""
Тесты ProcessManagerProcessApp — подкласс оркестратора прототипа (Task 3.2).

Проверяют:
  - _setup_topology_manager() вызывает configure_topology_manager
  - PROCESS_MANAGER_APP_CLASS_PATH соответствует реальному пути
  - Наследование от ProcessManagerProcess
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
