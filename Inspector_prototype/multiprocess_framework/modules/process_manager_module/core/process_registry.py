"""
ProcessRegistry — реестр процессов ОС + lifecycle + создание (Refactored).

Объединяет: registry (add, get) + lifecycle (start_all, stop_all, join_all) + create_and_register.
"""

import time
from multiprocessing import Process, Event
from typing import Dict, Any, Optional, List

from ..runner import run_process_function


def _create_process_impl(
    name: str,
    class_path: str,
    config: Dict[str, Any],
    priority: str,
    stop_event: Event,
    queue_registry,
    config_manager,
    shared_resources,
    logger,
) -> Optional[Process]:
    """Helper: создание Process ОС. Вынесено для соблюдения лимита строк."""
    try:
        if logger:
            logger._log_info(f"Creating process '{name}' from '{class_path}'")

        process_config = config or {}
        process_config = dict(process_config)
        process_config["name"] = name
        process_config["class"] = class_path

        if config_manager:
            try:
                process_config_obj = config_manager.get_config("processes")
                if process_config_obj:
                    processes_dict = process_config_obj.data.copy()
                    processes_dict[name] = process_config
                    process_config_obj.data.update(processes_dict)
                else:
                    config_manager.create_config("processes", {name: process_config})
            except Exception as e:
                if logger:
                    logger._log_error(f"ConfigManager update failed for '{name}': {e}")

        if queue_registry and not queue_registry.get_process_queues(name):
            queue_config = process_config.get("queues", {})
            queue_registry.create_and_register_queues(name, queue_config)

        queues = queue_registry.get_process_queues(name) if queue_registry else {}
        routing_map: Dict[str, Any] = {}
        if queue_registry:
            for pname in queue_registry.get_registered_processes():
                routing_map[pname] = queue_registry.get_process_queues(pname)
        process_data = shared_resources.get_process_data(name) if shared_resources else None
        custom = dict(process_data.custom) if process_data and process_data.custom else {}
        custom.setdefault("process_config", process_config)
        # Исключить non-picklable объекты (Event, ErrorManager и т.д.) для spawn
        for key in ("stop_event", "error_manager", "pause_event"):
            custom.pop(key, None)

        # memory_names других процессов — для consumer (processor, renderer, gui)
        # чтобы reinitialize_handles мог открыть camera_frame / rendered_frame
        all_process_memory: Dict[str, Dict[str, Any]] = {}
        if shared_resources:
            for pname in shared_resources.get_process_names():
                pd = shared_resources.get_process_data(pname)
                if pd and pd.custom and pd.custom.get("memory_names"):
                    mem = {k: v for k, v in pd.custom.items() if k in ("memory_names", "memory_params", "memory_index_usage", "memory_coll")}
                    if mem:
                        all_process_memory[pname] = mem
        custom["_all_process_memory"] = all_process_memory

        bundle = {
            "queues": queues,
            "config": process_config,
            "custom": custom,
            "routing_map": routing_map,
        }

        process = Process(
            target=run_process_function,
            args=(class_path, name, stop_event, bundle),
            name=name,
        )
        if logger:
            logger._log_info(f"Process '{name}' created (priority: {priority})")
        return process
    except Exception as e:
        if logger:
            logger._log_error(f"Failed to create process '{name}': {e}")
        import traceback
        traceback.print_exc()
        return None


class ProcessRegistry:
    """
    Реестр процессов ОС: хранение + lifecycle + создание.
    """

    def __init__(
        self,
        stop_event: Event,
        logger=None,
        queue_registry=None,
        config_manager=None,
        shared_resources=None,
    ) -> None:
        self.stop_event = stop_event
        self.logger = logger
        self.queue_registry = queue_registry
        self.config_manager = config_manager
        self.shared_resources = shared_resources
        self.os_processes: List[Process] = []

    def add_process(self, process: Process) -> None:
        """Добавить процесс в реестр."""
        self.os_processes.append(process)

    def get_process_by_name(self, name: str) -> Optional[Process]:
        """Получить процесс по имени."""
        for p in self.os_processes:
            if p.name == name:
                return p
        return None

    def create_and_register(
        self,
        name: str,
        class_path: str,
        config: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
    ) -> Optional[Process]:
        """Создать Process ОС и добавить в реестр."""
        process = _create_process_impl(
            name, class_path, config or {}, priority,
            self.stop_event, self.queue_registry, self.config_manager,
            self.shared_resources, self.logger,
        )
        if process:
            self.add_process(process)
        return process

    def start_all(self) -> None:
        """Запустить все процессы."""
        if self.logger:
            self.logger._log_info("Starting all processes...")
        for process in self.os_processes:
            try:
                process.start()
                if self.logger:
                    self.logger._log_info(f"Started OS process: {process.name} (PID: {process.pid})")
            except Exception as e:
                if self.logger:
                    self.logger._log_error(f"Failed to start process {process.name}: {e}")

    def stop_all(self, timeout: float = 5.0) -> None:
        """
        Graceful остановка всех процессов.

        Каскад для каждого процесса:
            stop_event.set() → join(timeout) → terminate → join(1s) → kill

        Args:
            timeout: Время ожидания join для каждого процесса (секунды).
        """
        if self.logger:
            self.logger._log_info(f"Stopping all processes (timeout={timeout}s)...")
        self.stop_event.set()
        self._join_all(timeout)

        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger._log_warning(
                        f"Process '{process.name}' did not stop in {timeout}s, terminating..."
                    )
                try:
                    process.terminate()
                    process.join(timeout=1.0)
                except Exception as e:
                    if self.logger:
                        self.logger._log_warning(f"Error terminating '{process.name}': {e}")

        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger._log_error(f"Force killing process '{process.name}'")
                try:
                    process.kill()
                except Exception as e:
                    if self.logger:
                        self.logger._log_error(f"Error killing '{process.name}': {e}")

        if self.logger:
            self.logger._log_info("All processes stopped")

    def _join_all(self, timeout: float = 5.0) -> None:
        """Ожидать завершения всех процессов с логированием."""
        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger._log_info(f"Waiting for process '{process.name}' (timeout={timeout}s)...")
                process.join(timeout=timeout)
                if process.is_alive() and self.logger:
                    self.logger._log_warning(f"Process '{process.name}' still alive after join")
