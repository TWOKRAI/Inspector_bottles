"""
Тесты для SystemLauncher.

Dict at Boundary: add_process(name, proc_dict) — только dict.
"""

import logging

import pytest

from ..launcher.system_launcher import SystemLauncher


class TestSystemLauncher:
    """Тесты SystemLauncher."""

    def test_init_empty(self) -> None:
        """Инициализация без config."""
        launcher = SystemLauncher()
        assert launcher._processes == []
        assert launcher._spawner is None

    def test_log_fallback_without_spawner(self, caplog, monkeypatch) -> None:
        """_log_info/_log_warning без spawner — логируется через stdlib logging."""
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
        monkeypatch.setattr(LoggerManager, "_instance", None)
        launcher = SystemLauncher()
        with caplog.at_level(logging.INFO):
            launcher._log_info("test info")
            launcher._log_warning("test warning")
        assert "[SystemLauncher]" in caplog.text

    def test_add_process_name_and_dict(self) -> None:
        """add_process(name, proc_dict)."""
        launcher = SystemLauncher()
        proc_dict = {"class": "mock.Process", "priority": "normal"}

        result = launcher.add_process("mock_process", proc_dict)

        assert result is launcher
        assert len(launcher._processes) == 1
        assert launcher._processes[0][0] == "mock_process"
        assert launcher._processes[0][1]["class"] == "mock.Process"

    def test_add_process_with_workers_in_dict(self) -> None:
        """add_process с workers в proc_dict."""
        launcher = SystemLauncher()
        proc_dict = {
            "class": "mock.Process",
            "workers": {
                "w1": {"class": "Worker1"},
                "w2": {"class": "Worker2"},
            },
        }

        launcher.add_process("proc_with_workers", proc_dict)

        assert len(launcher._processes) == 1
        assert "workers" in launcher._processes[0][1]
        assert "w1" in launcher._processes[0][1]["workers"]
        assert "w2" in launcher._processes[0][1]["workers"]

    def test_add_process_chain(self) -> None:
        """add_process возвращает self для цепочки."""
        launcher = SystemLauncher()

        launcher.add_process("p1", {"class": "P1"}).add_process(
            "p2", {"class": "P2"}
        )

        assert len(launcher._processes) == 2
        assert launcher._processes[0][0] == "p1"
        assert launcher._processes[1][0] == "p2"

    def test_get_status_without_spawner(self) -> None:
        """get_status() без spawner возвращает spawner_running: False."""
        launcher = SystemLauncher()
        status = launcher.get_status()

        assert status["spawner_running"] is False
        assert status["process"] is None

    def test_get_stats_without_spawner(self) -> None:
        """get_stats() без spawner."""
        launcher = SystemLauncher()
        stats = launcher.get_stats()

        assert "spawner" in stats
        assert stats["spawner"]["is_running"] is False

    def test_build_processes_config(self) -> None:
        """_build_processes_config() собирает dict из _processes."""
        launcher = SystemLauncher()
        launcher.add_process("mock_process", {"class": "mock.Process"})
        launcher.add_process("p2", {"class": "p2.Process"})

        config = launcher._build_processes_config()

        assert "mock_process" in config
        assert "p2" in config
        assert config["mock_process"]["class"] == "mock.Process"

    def test_add_process_normalizes_with_default_schema(self) -> None:
        """add_process нормализует proc_dict через DEFAULT_PROCESS_SCHEMA."""
        launcher = SystemLauncher()
        # Минимальный dict — только class
        launcher.add_process("minimal", {"class": "minimal.Process"})

        proc_dict = launcher._processes[0][1]
        assert proc_dict["class"] == "minimal.Process"
        assert "queues" in proc_dict
        assert proc_dict["queues"] == {}
        assert "priority" in proc_dict
        assert proc_dict["priority"] == "normal"
        assert "workers" in proc_dict
        assert proc_dict["workers"] == {}

    def test_init_with_stop_timeout(self) -> None:
        """Инициализация с кастомным stop_timeout."""
        launcher = SystemLauncher(stop_timeout=10.0)
        assert launcher._stop_timeout == 10.0

    def test_init_with_on_shutdown_callback(self) -> None:
        """Инициализация с on_shutdown callback."""
        from unittest.mock import MagicMock
        callback = MagicMock()
        launcher = SystemLauncher(on_shutdown=callback)
        assert launcher._on_shutdown is callback

    def test_create_spawner_passes_timeout(self) -> None:
        """_create_spawner передаёт stop_timeout в ProcessSpawner."""
        from unittest.mock import patch, MagicMock
        launcher = SystemLauncher(stop_timeout=7.0)
        with patch("multiprocess_framework.modules.process_manager_module.launcher.system_launcher.ProcessSpawner") as mock_spawner_cls:
            mock_spawner_cls.return_value = MagicMock()
            launcher._create_spawner({})
            call_kwargs = mock_spawner_cls.call_args[1]
            assert call_kwargs.get("stop_timeout") == 7.0

    def test_stop_calls_spawner_stop(self) -> None:
        """stop() вызывает spawner.stop()."""
        from unittest.mock import MagicMock
        launcher = SystemLauncher()
        mock_spawner = MagicMock()
        launcher._spawner = mock_spawner
        launcher.stop()
        mock_spawner.stop.assert_called_once()

    def test_shutdown_is_alias_for_stop(self) -> None:
        """shutdown() вызывает stop()."""
        from unittest.mock import MagicMock, patch
        launcher = SystemLauncher()
        with patch.object(launcher, "stop") as mock_stop:
            launcher.shutdown()
            mock_stop.assert_called_once()

    # --- orchestrator_class_path ---

    def test_init_default_orchestrator_class_path(self) -> None:
        """По умолчанию orchestrator_class_path = None."""
        launcher = SystemLauncher()
        assert launcher._orchestrator_class_path is None

    def test_init_custom_orchestrator_class_path(self) -> None:
        """Кастомный orchestrator_class_path сохраняется."""
        custom_path = "my_app.MyOrchestrator"
        launcher = SystemLauncher(orchestrator_class_path=custom_path)
        assert launcher._orchestrator_class_path == custom_path

    def test_create_spawner_forwards_orchestrator_class_path(self) -> None:
        """_create_spawner передаёт orchestrator_class_path в ProcessSpawner."""
        from unittest.mock import patch, MagicMock
        custom_path = "my_app.MyOrchestrator"
        launcher = SystemLauncher(orchestrator_class_path=custom_path)
        with patch("multiprocess_framework.modules.process_manager_module.launcher.system_launcher.ProcessSpawner") as mock_cls:
            mock_cls.return_value = MagicMock()
            launcher._create_spawner({})
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["orchestrator_class_path"] == custom_path

    def test_create_spawner_omits_orchestrator_when_none(self) -> None:
        """_create_spawner НЕ передаёт orchestrator_class_path если None."""
        from unittest.mock import patch, MagicMock
        launcher = SystemLauncher()  # orchestrator_class_path=None
        with patch("multiprocess_framework.modules.process_manager_module.launcher.system_launcher.ProcessSpawner") as mock_cls:
            mock_cls.return_value = MagicMock()
            launcher._create_spawner({})
            call_kwargs = mock_cls.call_args[1]
            assert "orchestrator_class_path" not in call_kwargs
