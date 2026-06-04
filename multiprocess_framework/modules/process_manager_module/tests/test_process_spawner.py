"""
Тесты для ProcessSpawner.

Проверяют создание, базовый API, graceful shutdown, signal handling.
"""

import signal
from unittest.mock import MagicMock, patch

from ..launcher.spawner import PROCESS_MANAGER_CLASS_PATH, ProcessSpawner


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

    def test_init_custom_stop_timeout(self) -> None:
        """Инициализация с кастомным stop_timeout."""
        spawner = ProcessSpawner(stop_timeout=10.0)
        assert spawner._stop_timeout == 10.0

    def test_init_on_shutdown_callback(self) -> None:
        """Инициализация с on_shutdown callback."""
        callback = MagicMock()
        spawner = ProcessSpawner(on_shutdown=callback)
        assert spawner._on_shutdown is callback

    def test_stop_without_process(self) -> None:
        """stop() без запущенного процесса не падает."""
        spawner = ProcessSpawner(processes_config={})
        spawner.stop(timeout=0.1)

    def test_wait_without_process(self) -> None:
        """wait() без процесса не падает."""
        spawner = ProcessSpawner(processes_config={})
        spawner.wait()

    def test_logger_none_before_launch(self) -> None:
        """До launch_orchestrator лёгкий логгер ещё не создан."""
        spawner = ProcessSpawner(processes_config={})
        assert spawner._logger is None

    def test_on_shutdown_called_on_stop(self) -> None:
        """on_shutdown callback вызывается при stop()."""
        callback = MagicMock()
        spawner = ProcessSpawner(on_shutdown=callback)
        spawner.stop()
        callback.assert_called_once()

    def test_on_shutdown_exception_does_not_propagate(self) -> None:
        """Исключение в on_shutdown не прерывает stop()."""
        callback = MagicMock(side_effect=RuntimeError("callback error"))
        spawner = ProcessSpawner(on_shutdown=callback)
        spawner.stop()  # не должен падать

    def test_signal_handler_calls_stop_not_exit(self) -> None:
        """_signal_handler вызывает stop() но не sys.exit()."""
        spawner = ProcessSpawner()
        spawner.stop = MagicMock()

        with patch("sys.exit") as mock_exit:
            spawner._signal_handler(signal.SIGINT, None)
            spawner.stop.assert_called_once()
            mock_exit.assert_not_called()

    def test_stop_with_alive_process_sets_stop_event(self) -> None:
        """stop() устанавливает stop_event при живом процессе."""
        spawner = ProcessSpawner()
        mock_process = MagicMock()
        mock_process.is_alive.return_value = True  # процесс жив — stop_event.set() будет вызван
        spawner._process = mock_process

        spawner.stop(timeout=0.1)
        # stop_event должен быть установлен
        assert spawner._stop_event.is_set()

    def test_stop_kills_if_still_alive_after_terminate(self) -> None:
        """stop() вызывает kill() если процесс не завершился после terminate."""
        spawner = ProcessSpawner(stop_timeout=0.1)
        mock_process = MagicMock()
        mock_process.is_alive.side_effect = [True, True, True]
        spawner._process = mock_process

        spawner.stop(timeout=0.1)
        mock_process.kill.assert_called_once()

    def test_stop_snapshots_descendants_before_kill(self) -> None:
        """stop() снимает поддерево ДО остановки PM и передаёт снимок guard'у.

        Снимок нужен psutil-fallback'у ProcessTreeGuard: после смерти PM обход по
        живым PPID не нашёл бы внуков. Авторитетный teardown — guard.kill_tree.
        """
        spawner = ProcessSpawner(stop_timeout=0.1)
        spawner._process = None  # PM отсутствует — фокус на снимке/делегировании
        sentinel = [MagicMock(pid=42)]
        spawner._snapshot_descendants = MagicMock(return_value=sentinel)
        spawner._guard = MagicMock()

        spawner.stop(timeout=0.1)

        spawner._snapshot_descendants.assert_called_once()
        spawner._guard.kill_tree.assert_called_once_with(sentinel)

    # --- orchestrator_class_path ---

    def test_init_default_orchestrator_class_path(self) -> None:
        """По умолчанию orchestrator_class_path = PROCESS_MANAGER_CLASS_PATH."""
        spawner = ProcessSpawner()
        assert spawner._orchestrator_class_path == PROCESS_MANAGER_CLASS_PATH

    def test_init_custom_orchestrator_class_path(self) -> None:
        """Кастомный orchestrator_class_path сохраняется."""
        custom_path = "my_app.orchestrator.MyOrchestrator"
        spawner = ProcessSpawner(orchestrator_class_path=custom_path)
        assert spawner._orchestrator_class_path == custom_path

    def test_launch_orchestrator_uses_custom_class_path(self) -> None:
        """launch_orchestrator() передаёт orchestrator_class_path в Process."""
        custom_path = "my_app.orchestrator.MyOrchestrator"
        spawner = ProcessSpawner(
            processes_config={},
            orchestrator_class_path=custom_path,
        )
        with (
            patch.object(spawner, "_platform") as _mock_platform,
            patch("multiprocess_framework.modules.process_manager_module.launcher.spawner.Process") as MockProcess,
            patch(
                "multiprocess_framework.modules.process_manager_module.launcher.spawner.SharedResourcesManager"
            ) as MockSRM,
            # ProcessTreeGuard мокаем — иначе launch создал бы реальный Job Object (Windows).
            patch("multiprocess_framework.modules.process_manager_module.launcher.spawner.ProcessTreeGuard"),
        ):
            MockSRM.return_value = MagicMock()
            mock_proc = MagicMock()
            MockProcess.return_value = mock_proc

            spawner.launch_orchestrator()

            # Первый аргумент args — class_path
            call_args = MockProcess.call_args
            assert call_args[1]["args"][0] == custom_path
