"""
ProcessManagerProcess — процесс-оркестратор (Refactored).

Наследуется от ProcessModule. Использует композицию: ProcessRegistry + ProcessPriority + ProcessStatus.
"""

from typing import Dict, Any, Optional

from ...process_module import ProcessModule
from ..core.process_registry import ProcessRegistry
from ..core.process_priority import ProcessPriority
from ..core.process_status import ProcessStatus
from ..monitor import ProcessMonitor
from multiprocessing import Event

from ..platforms import get_platform_adapter
from ...config_module import ConfigManager
from ...shared_resources_module import QueueRegistry
from ...console_module import ConsoleManager


class ProcessManagerProcess(ProcessModule):
    """
    Процесс-оркестратор: управляет всеми процессами системы.
    
    Композиция: ProcessRegistry + ProcessPriority + ProcessStatus + ProcessMonitor.
    """

    def __init__(
        self,
        name: str = "ProcessManager",
        shared_resources=None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, shared_resources, config or {})

        process_data = self.shared_resources.get_process_data(name) if self.shared_resources else None
        custom = process_data.custom if process_data and process_data.custom else {}
        self.stop_event = custom.get("stop_event") or Event()
        logger = self.logger_manager if hasattr(self, "logger_manager") else None

        config_manager = ConfigManager(manager_name="config_manager", process=None)
        config_manager.initialize()

        queue_registry = QueueRegistry(
            manager_name="queue_registry",
            process_state_registry=(
                self.shared_resources.process_state_registry if self.shared_resources else None
            ),
        )
        queue_registry.initialize()

        self._console_manager = ConsoleManager(
            manager_name="console_manager",
            managers={"logger": logger} if logger else {},
        )
        platform_adapter = get_platform_adapter()

        self._process_registry = ProcessRegistry(
            stop_event=self.stop_event,
            logger=self,
            queue_registry=queue_registry,
            config_manager=config_manager,
            shared_resources=shared_resources,
        )
        self._priority = ProcessPriority(logger=self, platform_adapter=platform_adapter)
        self._status = ProcessStatus(self._process_registry.os_processes)
        self._process_monitor = ProcessMonitor(self, poll_interval=0.5)

    def initialize(self) -> bool:
        """Инициализация: ProcessModule + создание процессов из config."""
        if not super().initialize():
            return False

        processes_config = self.get_config("processes_config") or {}
        if isinstance(processes_config, dict) and processes_config:
            self._create_processes_from_config(processes_config)

        self._process_monitor.start()
        return True

    def _create_processes_from_config(
        self, processes_config: Dict[str, Dict[str, Any]]
    ) -> None:
        """Двухфазно: очереди для всех, затем create + start."""
        valid = [
            (n, c) for n, c in processes_config.items()
            if isinstance(c, dict) and c.get("class")
        ]
        if not valid:
            return

        for name, proc_config in valid:
            if self.shared_resources:
                self.shared_resources.register_process_state(
                    name, config={"process": proc_config}
                )
            if self._process_registry.queue_registry:
                self._process_registry.queue_registry.create_and_register_queues(
                    name, proc_config.get("queues", {})
                )

        for name, proc_config in valid:
            priority = proc_config.get("priority", "normal")
            if self._process_registry.create_and_register(
                name, proc_config["class"], proc_config, priority
            ):
                self._priority.register_priority(name, priority)
                process = self._process_registry.get_process_by_name(name)
                if process:
                    process.start()
                    self._priority.apply_priority(process)

    def shutdown(self) -> bool:
        """Завершение: ProcessMonitor, ProcessRegistry.stop_all, консоли, ProcessModule."""
        if hasattr(self, "_process_monitor"):
            self._process_monitor.stop()
        if hasattr(self, "_process_registry"):
            self._process_registry.stop_all()
        if hasattr(self, "_console_manager") and self._console_manager:
            if hasattr(self._console_manager, "close_all"):
                self._console_manager.close_all()
            elif hasattr(self._console_manager, "shutdown"):
                self._console_manager.shutdown()
        return super().shutdown()

    def create_process(
        self,
        name: str,
        class_path: str,
        config: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
    ):
        """Создать и зарегистрировать процесс."""
        process = self._process_registry.create_and_register(
            name, class_path, config, priority
        )
        if process:
            self._priority.register_priority(name, priority)
        return process

    def start_process(self, process_name: Optional[str] = None) -> bool:
        """Запустить процесс или все."""
        if process_name:
            process = self._process_registry.get_process_by_name(process_name)
            if not process:
                return False
            process.start()
            self._priority.apply_priority(process)
            return True
        self._process_registry.start_all()
        for process in self._process_registry.os_processes:
            self._priority.apply_priority(process)
        return True

    def stop_process(self, process_name: Optional[str] = None) -> bool:
        """Остановить процесс или все."""
        if process_name:
            process = self._process_registry.get_process_by_name(process_name)
            if process and process.is_alive():
                process.terminate()
            return True
        self._process_registry.stop_all()
        return True

    def get_process_status(
        self, process_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Статус процесса или всех."""
        if process_name:
            process = self._process_registry.get_process_by_name(process_name)
            if not process:
                return {}
            status = self._status._get_status(process)
            if self.shared_resources:
                process_data = self.shared_resources.get_process_data(process_name)
                if process_data:
                    status["state"] = (
                        process_data.to_dict() if hasattr(process_data, "to_dict") else {}
                    )
            return status
        return self._status.get_all_status()

    def get_all_processes_status(self) -> Dict[str, Dict[str, Any]]:
        """Статусы всех процессов."""
        return self._status.get_all_status()
