"""
ProcessSpawner — создание и запуск ProcessManagerProcess (Refactored).

Объединяет логику Bootstrap: инфраструктура + Process ОС + старт + сигналы.
Один метод launch_orchestrator() — create + start.

Graceful shutdown:
    SIGINT/SIGTERM → _signal_handler → stop() → wait() возвращается естественно.
    Никакого sys.exit() в signal handler.
"""

import signal
from multiprocessing import Process, Event
from typing import Optional, Union, Dict, Any, Callable

from ..runner.process_runner import run_process_function
from ..platforms import get_platform_adapter
from ...shared_resources_module import SharedResourcesManager
from ...config_module import ConfigManager
from ...logger_module import LoggerManager
from ...error_module import ErrorManager

PROCESS_MANAGER_CLASS_PATH = (
    "multiprocess_framework.modules.process_manager_module."
    "process.process_manager_process.ProcessManagerProcess"
)


class ProcessSpawner:
    """
    Создание и запуск ProcessManagerProcess.

    launch_orchestrator() — создаёт инфраструктуру, Process ОС, запускает, настраивает сигналы.

    Graceful shutdown:
        SIGINT/SIGTERM вызывают stop() без sys.exit().
        wait() возвращается естественно после завершения процесса.

    Args:
        processes_config: Конфиг процессов для передачи в ProcessManagerProcess.
        platform_adapter: Адаптер платформы (по умолчанию — автоопределение).
        stop_timeout: Время ожидания graceful stop перед terminate (секунды).
        on_shutdown: Callback, вызываемый при завершении системы.
    """

    def __init__(
        self,
        processes_config: Union[Dict[str, Any], None] = None,
        platform_adapter=None,
        stop_timeout: float = 5.0,
        on_shutdown: Optional[Callable[[], None]] = None,
    ) -> None:
        self._processes_config = processes_config or {}
        self._platform = platform_adapter or get_platform_adapter()
        self._stop_event = Event()
        self._process: Optional[Process] = None
        self._shared_resources: Optional[SharedResourcesManager] = None
        self._logger: Optional[LoggerManager] = None
        self._error_manager: Optional[ErrorManager] = None
        self._stop_timeout = stop_timeout
        self._on_shutdown = on_shutdown

    def launch_orchestrator(self) -> bool:
        """
        Создать инфраструктуру, Process ОС, запустить.

        Создаёт:
            - SharedResourcesManager (общая память между процессами)
            - ConfigManager (конфиг инфраструктуры)
            - LoggerManager (логирование spawner)
            - Process ОС с run_process_function как target

        Returns:
            True если успешно.
        """
        self._platform.setup_multiprocessing()
        self._shared_resources = SharedResourcesManager(manager_name="shared_resources")
        self._shared_resources.initialize()

        config_manager = ConfigManager(manager_name="config_manager", process=None)
        config_manager.initialize()

        self._logger = LoggerManager(
            manager_name="spawner_logger",
            config_manager=config_manager,
        )
        self._logger.initialize()

        self._error_manager = ErrorManager(manager_name="spawner_errors")
        self._error_manager.initialize()

        process_config = {"processes_config": self._processes_config}
        bundle = {
            "queues": {},
            "config": process_config,
            "custom": {"process_config": process_config, "stop_event": self._stop_event},
        }

        self._process = Process(
            target=run_process_function,
            args=(PROCESS_MANAGER_CLASS_PATH, "ProcessManager", self._stop_event, bundle),
            name="ProcessManager",
        )
        self._process.start()

        self._setup_signals()
        return True

    def _setup_signals(self) -> None:
        """Зарегистрировать обработчики SIGINT, SIGTERM."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        """
        Обработчик сигналов завершения.

        Вызывает stop() и позволяет wait() вернуться естественно.
        Никакого sys.exit() — это позволяет корректно завершить все ресурсы.
        """
        if self._logger:
            self._logger.warning(
                f"Received signal {signum}, shutting down...",
                module="spawner",
            )
        else:
            print(f"\n[*] Received signal {signum}, shutting down...")
        self.stop()
        # Намеренно не вызываем sys.exit() — wait() вернётся естественно

    def stop(self, timeout: Optional[float] = None) -> None:
        """
        Остановить ProcessManagerProcess и освободить ресурсы.

        Каскад: stop_event.set() → join(graceful_timeout) → terminate → join → kill.

        Args:
            timeout: Время ожидания после terminate (секунды). По умолчанию _stop_timeout.
        """
        effective_timeout = timeout if timeout is not None else self._stop_timeout
        graceful_timeout = min(effective_timeout, 3.0)

        if self._logger:
            self._logger.info("Stopping ProcessManager...", module="spawner")

        if self._process and self._process.is_alive():
            self._stop_event.set()
            self._process.join(timeout=graceful_timeout)

            if self._process.is_alive():
                if self._logger:
                    self._logger.warning(
                        f"Process did not stop in {graceful_timeout}s, terminating...",
                        module="spawner",
                    )
                self._process.terminate()
                self._process.join(timeout=effective_timeout)

            if self._process.is_alive():
                if self._logger:
                    self._logger.warning("Force killing ProcessManager", module="spawner")
                self._process.kill()

        if self._on_shutdown:
            try:
                self._on_shutdown()
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"on_shutdown callback error: {e}", module="spawner")

        if self._shared_resources:
            self._shared_resources.shutdown()

        if self._error_manager:
            self._error_manager.shutdown()

        if self._logger:
            self._logger.info("ProcessManager stopped", module="spawner")

    def wait(self) -> None:
        """Ожидать завершения ProcessManagerProcess."""
        if self._process:
            self._process.join()

    def is_running(self) -> bool:
        """Проверка, запущен ли ProcessManagerProcess."""
        return self._process is not None and self._process.is_alive()

    def get_process(self) -> Optional[Process]:
        """Получить Process ОС (для get_status)."""
        return self._process

    def get_shared_resources(self) -> Optional[SharedResourcesManager]:
        """Получить SharedResourcesManager."""
        return self._shared_resources

    def get_logger(self) -> Optional[LoggerManager]:
        """Получить LoggerManager (создаётся в launch_orchestrator)."""
        return self._logger

    def get_error_manager(self) -> Optional[ErrorManager]:
        """Получить ErrorManager (создаётся в launch_orchestrator)."""
        return self._error_manager
