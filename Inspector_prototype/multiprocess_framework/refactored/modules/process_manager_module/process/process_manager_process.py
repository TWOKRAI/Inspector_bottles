"""
ProcessManagerProcess — процесс-оркестратор (Refactored).

Наследуется от ProcessModule. Использует композицию:
    ProcessRegistry + ProcessPriority + ProcessStatus + ProcessMonitor.

Порядок shutdown:
    ProcessMonitor → ProcessRegistry.stop_all → WorkerManager → ConsoleManager → super
"""

from typing import Dict, Any, Optional

from ...process_module import ProcessModule
from ..core.process_registry import ProcessRegistry
from ..core.process_priority import ProcessPriority
from ..core.process_status import ProcessStatus
from ..monitor import ProcessMonitor
from multiprocessing import Event

from ..platforms import get_platform_adapter
from ...shared_resources_module import QueueRegistry
from ...console_module import ConsoleManager


class ProcessManagerProcess(ProcessModule):
    """
    Процесс-оркестратор: управляет всеми процессами системы.

    Реализует IProcessManagerProcess.
    Композиция: ProcessRegistry + ProcessPriority + ProcessStatus + ProcessMonitor.

    Жизненный цикл:
        __init__  → _create_components()
        initialize() → super().initialize() → _create_processes_from_config() → monitor.start()
        shutdown() → monitor.stop() → registry.stop_all() → console.shutdown() → super()
    """

    def __init__(
        self,
        name: str = "ProcessManager",
        shared_resources=None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, shared_resources, config or {})
        self._create_components()

    def _create_components(self) -> None:
        """Создать внутренние компоненты оркестратора."""
        process_data = (
            self.shared_resources.get_process_data(self.name)
            if self.shared_resources else None
        )
        custom = process_data.custom if process_data and process_data.custom else {}
        self.stop_event = custom.get("stop_event") or Event()

        # QueueRegistry: используем из shared_resources если доступен
        queue_registry = self._resolve_queue_registry()

        platform_adapter = get_platform_adapter()

        self._process_registry = ProcessRegistry(
            stop_event=self.stop_event,
            logger=self,
            queue_registry=queue_registry,
            config_manager=None,
            shared_resources=self.shared_resources,
        )
        self._priority = ProcessPriority(logger=self, platform_adapter=platform_adapter)
        self._status = ProcessStatus(self._process_registry.os_processes)
        self._process_monitor = ProcessMonitor(self, poll_interval=0.5)
        self._console_manager: Optional[ConsoleManager] = None

    def _resolve_queue_registry(self):
        """Получить QueueRegistry из shared_resources или создать новый."""
        if self.shared_resources and hasattr(self.shared_resources, "process_state_registry"):
            try:
                registry = self.shared_resources.process_state_registry
                if registry and hasattr(registry, "queue_registry"):
                    return registry.queue_registry
            except Exception:
                pass
        # Fallback: создать локальный QueueRegistry
        queue_registry = QueueRegistry(
            manager_name="queue_registry",
            process_state_registry=(
                self.shared_resources.process_state_registry
                if self.shared_resources else None
            ),
        )
        queue_registry.initialize()
        return queue_registry

    def _setup_console_manager(self) -> None:
        """Создать ConsoleManager только если включён в конфиге."""
        console_enabled = self.get_config("console_enabled")
        if not console_enabled:
            return
        logger = self.logger_manager if hasattr(self, "logger_manager") else None
        self._console_manager = ConsoleManager(
            manager_name="console_manager",
            managers={"logger": logger} if logger else {},
        )

    def initialize(self) -> bool:
        """Инициализация: ProcessModule + создание процессов из config + запуск монитора."""
        try:
            if not super().initialize():
                return False

            self._setup_console_manager()
            self._register_builtin_commands()

            processes_config = self.get_config("processes_config") or {}
            if isinstance(processes_config, dict) and processes_config:
                self._create_processes_from_config(processes_config)

            self._process_monitor.start()
            return True
        except Exception as exc:
            self._handle_critical_error(exc, "initialize")
            return False

    def _register_builtin_commands(self) -> None:
        """Зарегистрировать встроенные команды системы."""
        if not self.command_manager:
            return

        commands = {
            "process.list": (self._cmd_process_list, "Список всех процессов и статусов"),
            "process.start": (self._cmd_process_start, "Запустить именованный процесс"),
            "process.stop": (self._cmd_process_stop, "Остановить именованный процесс"),
            "process.status": (self._cmd_process_status, "Статус именованного процесса"),
            "system.shutdown": (self._cmd_system_shutdown, "Завершить систему"),
            "system.stats": (self._cmd_system_stats, "Статистика системы"),
        }

        for cmd_name, (handler, description) in commands.items():
            self.command_manager.register_command(
                cmd_name,
                handler,
                metadata={"description": description},
                tags=["system"],
            )

    # -------------------------------------------------------------------------
    # Обработчики встроенных команд
    # -------------------------------------------------------------------------

    def _cmd_process_list(self, **kwargs) -> dict:
        """Вернуть список всех процессов и их статусы."""
        return self.get_all_processes_status()

    def _cmd_process_start(self, process_name: str = "", **kwargs) -> dict:
        """Запустить именованный процесс."""
        if not process_name:
            return {"error": "process_name required"}
        success = self.start_process(process_name)
        return {"success": success, "process_name": process_name}

    def _cmd_process_stop(self, process_name: str = "", **kwargs) -> dict:
        """Остановить именованный процесс."""
        if not process_name:
            return {"error": "process_name required"}
        success = self.stop_process(process_name)
        return {"success": success, "process_name": process_name}

    def _cmd_process_status(self, process_name: str = "", **kwargs) -> dict:
        """Статус именованного процесса."""
        if not process_name:
            return {"error": "process_name required"}
        return self.get_process_status(process_name)

    def _cmd_system_shutdown(self, **kwargs) -> dict:
        """Запустить завершение системы."""
        self._log_info("System shutdown requested via command")
        self.stop_event.set()
        return {"success": True, "message": "Shutdown initiated"}

    def _cmd_system_stats(self, **kwargs) -> dict:
        """Статистика системы."""
        stats: dict = {}
        if hasattr(self, "_process_monitor"):
            stats["monitor"] = self._process_monitor.get_stats()
        stats["processes"] = self.get_all_processes_status()
        return stats

    def _handle_critical_error(self, exc: Exception, context: str) -> None:
        """Логировать критическую ошибку через error_module и запустить shutdown."""
        error_manager = self._get_error_manager()
        if error_manager:
            error_manager.log_exception(
                exc,
                f"Critical error in ProcessManagerProcess.{context}",
                module="process_manager",
            )
        else:
            import traceback
            self._log_error(f"Critical error in {context}: {exc}")
            traceback.print_exc()
        self.shutdown()

    def _get_error_manager(self):
        """Получить ErrorManager из shared_resources если доступен."""
        if not self.shared_resources:
            return None
        try:
            process_data = self.shared_resources.get_process_data(self.name)
            if process_data and process_data.custom:
                return process_data.custom.get("error_manager")
        except Exception:
            pass
        return None

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
        """
        Завершение с явным порядком:
            1. ProcessMonitor
            2. ProcessRegistry.stop_all (дочерние процессы)
            3. ConsoleManager
            4. super().shutdown() (WorkerManager, RouterManager и т.д.)
        """
        if hasattr(self, "_process_monitor"):
            self._process_monitor.stop()
        if hasattr(self, "_process_registry"):
            shutdown_timeout = self.get_config("shutdown_timeout") or 5.0
            self._process_registry.stop_all(timeout=shutdown_timeout)
        if self._console_manager is not None:
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
        """
        Остановить процесс или все.

        Graceful: stop_event → join(timeout) → terminate.
        """
        if process_name:
            process = self._process_registry.get_process_by_name(process_name)
            if process and process.is_alive():
                self._process_registry.stop_event.set()
                stop_timeout = self.get_config("stop_process_timeout") or 3.0
                process.join(timeout=stop_timeout)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1.0)
                if process.is_alive():
                    process.kill()
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
