"""
Тесты для SystemLauncher.wait_until_ready() (ADR-116).

Проверяют три сценария:
1. Все процессы успешно стартовали — возвращает True.
2. Таймаут истёк — возвращает False.
3. Процесс упал во время инициализации — возвращает False (ранний выход).
"""

import threading
import time
from unittest.mock import MagicMock, patch


from ..launcher.system_launcher import SystemLauncher


class TestWaitUntilReady:
    """Тесты SystemLauncher.wait_until_ready()."""

    def test_returns_false_when_start_not_called(self) -> None:
        """wait_until_ready() без предварительного start() возвращает False."""
        launcher = SystemLauncher()
        assert launcher.wait_until_ready(timeout=1.0) is False

    def test_returns_true_when_event_already_set(self) -> None:
        """Если system_ready_event уже выставлен — мгновенный возврат True."""
        launcher = SystemLauncher()
        # Имитируем, что start() был вызван: подставляем mock spawner
        mock_spawner = MagicMock()
        mock_spawner.is_running.return_value = True
        launcher._spawner = mock_spawner
        # Выставляем event заранее
        launcher._system_ready_event.set()

        start = time.monotonic()
        result = launcher.wait_until_ready(timeout=5.0)
        elapsed = time.monotonic() - start

        assert result is True
        # Должен вернуться практически мгновенно (< 0.5с)
        assert elapsed < 0.5

    def test_returns_true_when_event_set_during_wait(self) -> None:
        """Event выставляется во время ожидания — возвращает True до таймаута."""
        launcher = SystemLauncher()
        mock_spawner = MagicMock()
        mock_spawner.is_running.return_value = True
        launcher._spawner = mock_spawner

        # Выставим event через 0.3с из отдельного потока
        def set_event_delayed():
            time.sleep(0.3)
            launcher._system_ready_event.set()

        thread = threading.Thread(target=set_event_delayed, daemon=True)
        thread.start()

        start = time.monotonic()
        result = launcher.wait_until_ready(timeout=5.0)
        elapsed = time.monotonic() - start

        assert result is True
        # Должен вернуться примерно через 0.3с (< 1.0с точно)
        assert elapsed < 1.0
        thread.join(timeout=1.0)

    def test_returns_false_on_timeout(self) -> None:
        """Таймаут истёк, event не выставлен — возвращает False."""
        launcher = SystemLauncher()
        mock_spawner = MagicMock()
        mock_spawner.is_running.return_value = True
        launcher._spawner = mock_spawner
        # Event НЕ выставляется

        start = time.monotonic()
        result = launcher.wait_until_ready(timeout=0.3)
        elapsed = time.monotonic() - start

        assert result is False
        # Должен вернуться примерно через 0.3с (допуск ±0.2с)
        assert 0.2 < elapsed < 0.6

    def test_returns_false_when_process_crashes_during_init(self) -> None:
        """ProcessManager упал — spawner.is_running() == False → ранний выход с False."""
        launcher = SystemLauncher()
        mock_spawner = MagicMock()
        # Сначала жив, потом «умирает»
        call_count = 0

        def is_running_side_effect():
            nonlocal call_count
            call_count += 1
            # Первые 3 вызова — жив, потом мёртв
            return call_count <= 3

        mock_spawner.is_running.side_effect = is_running_side_effect
        launcher._spawner = mock_spawner
        # Event НЕ выставляется

        start = time.monotonic()
        result = launcher.wait_until_ready(timeout=5.0)
        elapsed = time.monotonic() - start

        assert result is False
        # Должен выйти рано, задолго до таймаута 5с
        assert elapsed < 2.0

    def test_returns_false_when_process_immediately_dead(self) -> None:
        """ProcessManager мёртв с самого начала — мгновенный False."""
        launcher = SystemLauncher()
        mock_spawner = MagicMock()
        mock_spawner.is_running.return_value = False
        launcher._spawner = mock_spawner

        start = time.monotonic()
        result = launcher.wait_until_ready(timeout=5.0)
        elapsed = time.monotonic() - start

        assert result is False
        # Мгновенный выход
        assert elapsed < 0.5

    def test_system_ready_event_is_multiprocessing_event(self) -> None:
        """_system_ready_event — экземпляр multiprocessing.Event (pickle-safe)."""
        launcher = SystemLauncher()
        event = launcher._system_ready_event
        # multiprocessing.Event имеет методы set/is_set/wait/clear
        assert hasattr(event, "set")
        assert hasattr(event, "is_set")
        assert hasattr(event, "wait")
        assert hasattr(event, "clear")
        assert not event.is_set()

    def test_create_spawner_passes_system_ready_event(self) -> None:
        """_create_spawner передаёт system_ready_event в ProcessSpawner."""
        launcher = SystemLauncher()
        with patch(
            "multiprocess_framework.modules.process_manager_module.launcher.system_launcher.ProcessSpawner"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            launcher._create_spawner({})
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs.get("system_ready_event") is launcher._system_ready_event
