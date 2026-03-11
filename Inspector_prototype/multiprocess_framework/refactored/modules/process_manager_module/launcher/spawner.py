"""
ProcessSpawner — создание и запуск ProcessManagerProcess (Refactored).

Объединяет логику Bootstrap: инфраструктура + Process ОС + старт + сигналы.
Один метод launch_orchestrator() — create + start.
"""

import sys
import signal
from multiprocessing import Process, Event
from typing import Optional, Union, Dict, Any

from ..runner.process_runner import run_process_function
from ..platforms import get_platform_adapter
from ...shared_resources_module import SharedResourcesManager
from ...config_module import ConfigManager
from ...logger_module import LoggerManager

PROCESS_MANAGER_CLASS_PATH = (
    "multiprocess_framework.refactored.modules.process_manager_module."
    "process.process_manager_process.ProcessManagerProcess"
)


class ProcessSpawner:
    """
    Создание и запуск ProcessManagerProcess.
    
    launch_orchestrator() — создаёт инфраструктуру, Process ОС, запускает, настраивает сигналы.
    """

    def __init__(
        self,
        processes_config: Union[Dict[str, Any], None] = None,
        platform_adapter=None,
    ) -> None:
        self._processes_config = processes_config or {}
        self._platform = platform_adapter or get_platform_adapter()
        self._stop_event = Event()
        self._process: Optional[Process] = None
        self._shared_resources: Optional[SharedResourcesManager] = None
        self._logger: Optional[LoggerManager] = None

    def launch_orchestrator(self) -> bool:
        """
        Создать инфраструктуру, Process ОС, запустить.
        
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
        """Обработчики SIGINT, SIGTERM."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        if self._logger:
            self._logger.warning(
                f"Received signal {signum}, shutting down...",
                module="spawner",
            )
        else:
            print(f"\n[*] Received signal {signum}, shutting down...")
        self.stop()
        sys.exit(0)

    def stop(self, timeout: float = 3.0) -> None:
        """Остановить ProcessManagerProcess и освободить ресурсы."""
        if self._process and self._process.is_alive():
            self._stop_event.set()
            self._process.terminate()
            self._process.join(timeout=timeout)
            if self._process.is_alive():
                self._process.kill()
        if self._shared_resources:
            self._shared_resources.shutdown()

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
