"""
Реестр состояний процессов для межпроцессного взаимодействия.

Перенесён из process_module.state в shared_resources_module.state —
разрыв циклической зависимости process_module <-> shared_resources_module.

Хранит состояния всех процессов:
- Статусы процессов (ready, initializing, running, stopping, error)
- События процессов (Event объекты)
- Очереди процессов (Queue объекты)
- Метаданные процессов
- Кастомные данные для расширения
"""

import time
from typing import Dict, Any, Optional
from multiprocessing import Queue, Event

from .process_data import ProcessData


class ProcessStateRegistry:
    """
    Реестр состояний процессов (без Manager() и Lock()).

    Использует простой словарь Dict[str, ProcessData] для хранения данных процессов.
    Queue и Event из multiprocessing — pickle-safe нативно.

    Перенесён из process_module для устранения циклической зависимости.
    EventType импортируется локально из events.event_manager (в том же модуле).
    """

    STATUS_INITIALIZING = "initializing"
    STATUS_READY = "ready"
    STATUS_RUNNING = "running"
    STATUS_STOPPING = "stopping"
    STATUS_ERROR = "error"

    def __init__(self, event_manager: Optional[Any] = None):
        """
        Args:
            event_manager: EventManager для отправки событий при изменениях (опционально)
        """
        self.states: Dict[str, ProcessData] = {}
        self.event_manager = event_manager

    def _emit(self, event_type_name: str, **kwargs):
        """Отправить событие через EventManager (без lazy import — EventType локальный)."""
        if not self.event_manager:
            return
        try:
            from ..events.event_manager import EventType
            event_type = getattr(EventType, event_type_name, None)
            if event_type is not None:
                self.event_manager.emit_event(event_type, **kwargs)
        except Exception:
            pass

    def register_process(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        queue_names: Optional[Dict[str, str]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Регистрация процесса с начальным состоянием.

        Returns:
            bool: True если регистрация успешна
        """
        try:
            if process_name in self.states:
                process_data = self.states[process_name]
                if initial_state:
                    if "status" in initial_state:
                        process_data.status = initial_state["status"]
                        process_data.update_timestamp()
                    if "metadata" in initial_state:
                        process_data.metadata.update(initial_state["metadata"])
                        process_data.update_timestamp()
                    if "custom" in initial_state:
                        process_data.custom.update(initial_state["custom"])
                        process_data.update_timestamp()
                if config is not None and isinstance(config, dict):
                    self._apply_config_to_data(process_data, config)
            else:
                status = initial_state.get("status", self.STATUS_INITIALIZING) if initial_state else self.STATUS_INITIALIZING
                metadata = initial_state.get("metadata", {}) if initial_state else {}
                custom = initial_state.get("custom", {}) if initial_state else {}

                process_data = ProcessData(
                    name=process_name,
                    status=status,
                    metadata=metadata,
                    custom=custom,
                )

                if config and isinstance(config, dict):
                    self._apply_config_to_data(process_data, config)

                self.states[process_name] = process_data
                self._emit("PROCESS_REGISTERED", process_name=process_name, state=process_data.to_dict())

            return True
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to register process '{process_name}': {e}")
            return False

    def _apply_config_to_data(self, process_data: ProcessData, config: Dict[str, Any]):
        """Применить конфигурацию к ProcessData."""
        if "process" in config:
            process_data.custom["process_config"] = config["process"].copy()
        if "managers" in config:
            process_data.custom["component_managers_config"] = config["managers"].copy()
        if "modules" in config:
            process_data.custom["modules_config"] = config["modules"].copy()
        if "custom" in config:
            process_data.custom["config_custom"] = config["custom"].copy()
        process_data.update_timestamp()

    def register_process_with_config(
        self,
        process_name: str,
        config: Any,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Регистрация процесса с конфигурацией (ProcessConfiguration или dict)."""
        if hasattr(config, "process") and hasattr(config, "to_dict"):
            config = config.to_dict()
        elif not isinstance(config, dict):
            config = {}
        return self.register_process(process_name, initial_state=initial_state or {}, config=config)

    def update_state(
        self,
        process_name: str,
        status: Optional[str] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        queues: Optional[Dict[str, str]] = None,
        custom: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Обновление состояния процесса."""
        try:
            if process_name not in self.states:
                return self.register_process(process_name, {
                    "status": status or self.STATUS_INITIALIZING,
                    "metadata": metadata or {},
                    "custom": custom or {},
                })

            process_data = self.states[process_name]
            old_status = process_data.status if status is not None else None

            if status is not None:
                process_data.status = status
                process_data.update_timestamp()
                if old_status != status:
                    self._emit(
                        "PROCESS_STATE_CHANGED",
                        process_name=process_name,
                        old_status=old_status,
                        new_status=status,
                        state=process_data.to_dict(),
                    )

            if metadata is not None:
                process_data.metadata.update(metadata)
                process_data.update_timestamp()

            if custom is not None:
                process_data.custom.update(custom)
                process_data.update_timestamp()

            return True
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to update state for '{process_name}': {e}")
            return False

    def add_queue(self, process_name: str, queue_type: str, queue: Queue) -> bool:
        """Добавляет очередь в процесс."""
        try:
            if process_name not in self.states:
                self.register_process(process_name)
            self.states[process_name].add_queue(queue_type, queue)
            self._emit("QUEUE_ADDED", process_name=process_name, queue_type=queue_type)
            return True
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to add queue '{queue_type}' to '{process_name}': {e}")
            return False

    def add_event(self, process_name: str, event_name: str, event: Event) -> bool:
        """Добавляет событие в процесс."""
        try:
            if process_name not in self.states:
                self.register_process(process_name)
            self.states[process_name].add_event(event_name, event)
            self._emit("EVENT_ADDED", process_name=process_name, event_name=event_name)
            return True
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to add event '{event_name}' to '{process_name}': {e}")
            return False

    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        """Получает очередь процесса по типу."""
        if process_name not in self.states:
            return None
        return self.states[process_name].get_queue(queue_type)

    def get_event(self, process_name: str, event_name: str) -> Optional[Event]:
        """Получает событие процесса по имени."""
        if process_name not in self.states:
            return None
        return self.states[process_name].get_event(event_name)

    def get_state(self, process_name: str) -> Optional[Dict[str, Any]]:
        """Получение состояния процесса как dict."""
        try:
            if process_name not in self.states:
                return None
            return self.states[process_name].to_dict()
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to get state for '{process_name}': {e}")
            return None

    def get_process_data(self, process_name: str) -> Optional[ProcessData]:
        """Получает ProcessData объект процесса."""
        return self.states.get(process_name)

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Получение всех состояний процессов."""
        try:
            return {name: data.to_dict() for name, data in self.states.items()}
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to get all states: {e}")
            return {}

    def get_all_process_data(self) -> Dict[str, ProcessData]:
        """Получает все ProcessData объекты."""
        return self.states.copy()

    def get_process_names(self) -> list:
        """Получение списка всех зарегистрированных процессов."""
        try:
            return list(self.states.keys())
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to get process names: {e}")
            return []

    def unregister_process(self, process_name: str) -> bool:
        """Удаление процесса из реестра."""
        try:
            if process_name in self.states:
                self._emit("PROCESS_UNREGISTERED", process_name=process_name)
                del self.states[process_name]
                return True
            return False
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to unregister process '{process_name}': {e}")
            return False

    def has_process(self, process_name: str) -> bool:
        """Проверка наличия процесса в реестре."""
        try:
            return process_name in self.states
        except Exception:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики реестра."""
        try:
            states = self.get_all_states()
            status_counts: Dict[str, int] = {}
            for state in states.values():
                status = state.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            return {
                "total_processes": len(states),
                "status_counts": status_counts,
                "processes": list(states.keys()),
            }
        except Exception as e:
            print(f"ProcessStateRegistry: Failed to get stats: {e}")
            return {"total_processes": 0, "status_counts": {}, "processes": []}
