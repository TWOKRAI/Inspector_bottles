"""
Тесты для ProcessSpawner.

Проверяют создание и базовый API.
"""

import pytest

from ..launcher.spawner import ProcessSpawner


class TestProcessSpawner:
    """Тесты ProcessSpawner."""

    def test_init(self) -> None:
        """Инициализация с processes_config."""
        spawner = ProcessSpawner(processes_config={"p1": {"class": "test.Process"}})
        assert spawner._processes_config == {"p1": {"class": "test.Process"}}
        assert spawner._process is None
        assert spawner.get_process() is None
        assert not spawner.is_running()

    def test_init_empty_config(self) -> None:
        """Инициализация с пустым config."""
        spawner = ProcessSpawner()
        assert spawner._processes_config == {}

    def test_stop_without_process(self) -> None:
        """stop() без запущенного процесса не падает."""
        spawner = ProcessSpawner(processes_config={})
        spawner.stop(timeout=0.1)

    def test_wait_without_process(self) -> None:
        """wait() без процесса не падает."""
        spawner = ProcessSpawner(processes_config={})
        spawner.wait()

    def test_get_logger_before_launch(self) -> None:
        """get_logger() до launch_orchestrator возвращает None."""
        spawner = ProcessSpawner(processes_config={})
        assert spawner.get_logger() is None
