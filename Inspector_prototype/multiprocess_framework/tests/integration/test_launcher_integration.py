"""
Тесты интеграции SystemLauncher с ProcessSpawner.

Проверяют взаимодействие между Launcher и ProcessSpawner (refactored API).
"""

import pytest
from unittest.mock import Mock
from multiprocess_framework.refactored.modules.process_manager_module import (
    SystemLauncher,
    ProcessSpawner,
)


class TestLauncherIntegration:
    """Тесты интеграции SystemLauncher"""

    def test_launcher_creation_default(self):
        """Тест создания Launcher без spawner (до run/start)"""
        launcher = SystemLauncher()

        assert launcher._spawner is None
        assert launcher._processes == []

    def test_launcher_add_process_and_get_status(self):
        """Тест добавления процесса и получения статуса"""
        launcher = SystemLauncher()
        launcher.add_process("test_process", {"name": "test_process"})

        assert len(launcher._processes) == 1
        status = launcher.get_status()
        assert isinstance(status, dict)
        assert "spawner_running" in status
        assert status["spawner_running"] is False

    def test_launcher_get_status_without_spawner(self):
        """Тест получения статуса без запущенного spawner"""
        launcher = SystemLauncher()

        status = launcher.get_status()
        assert isinstance(status, dict)
        assert status["spawner_running"] is False
        assert status["process"] is None

    def test_launcher_get_stats_without_spawner(self):
        """Тест получения статистики без spawner"""
        launcher = SystemLauncher()

        stats = launcher.get_stats()
        assert isinstance(stats, dict)
        assert "spawner" in stats
        assert stats["spawner"]["is_running"] is False

    def test_launcher_spawner_access_after_run(self):
        """Тест доступа к ProcessSpawner после run (мок)"""
        launcher = SystemLauncher()
        launcher.add_process("test", {"name": "test"})

        # Мокаем ProcessSpawner чтобы не запускать реальные процессы
        mock_spawner = Mock(spec=ProcessSpawner)
        mock_spawner.is_running.return_value = True
        mock_spawner.get_process.return_value = None
        mock_spawner.get_shared_resources.return_value = None
        launcher._spawner = mock_spawner

        assert hasattr(launcher._spawner, "launch_orchestrator")
        assert hasattr(launcher._spawner, "stop")
        assert hasattr(launcher._spawner, "wait")
        assert hasattr(launcher._spawner, "is_running")
