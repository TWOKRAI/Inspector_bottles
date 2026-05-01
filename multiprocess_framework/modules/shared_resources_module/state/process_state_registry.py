"""
ProcessStateRegistry — реестр runtime-состояний процессов.

Dict[str, ProcessData] защищён threading.RLock (reentrant, т.к. update_state
вызывает register_process). Инвариант: используется только из одного процесса.
Queue и Event из multiprocessing pickle-safe нативно.

Перенесён из process_module для устранения циклической зависимости.
"""

import threading
from typing import Any, Dict, List, Optional
from multiprocessing import Queue, Event

from .process_data import ProcessData
from ..types import ProcessStatus, ProcessDataDict
from .interfaces import IProcessStateRegistry


class ProcessStateRegistry(IProcessStateRegistry):
    """
    Реестр runtime-состояний процессов.

    Хранит Dict[str, ProcessData] под threading.RLock. Является единственным
    source of truth для Queue/Event ссылок — QueueRegistry и MemoryManager
    делегируют сюда.
    """

    def __init__(
        self,
        event_manager: Optional[Any] = None,
        logger: Any = None,
    ) -> None:
        self.states: Dict[str, ProcessData] = {}
        self.event_manager = event_manager
        self._logger = logger
        self._lock = threading.RLock()

    def __getstate__(self) -> dict:
        """Исключить RLock из pickle: он пересоздаётся в __setstate__."""
        state = self.__dict__.copy()
        del state["_lock"]
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Внутренние утилиты
    # ------------------------------------------------------------------

    def _log(self, level: str, msg: str) -> None:
        if self._logger is not None:
            method = getattr(self._logger, f"_log_{level}", None)
            if callable(method):
                method(msg)

    def _emit(self, event_type_name: str, **kwargs: Any) -> None:
        """Отправить событие через EventManager (если подключён)."""
        if not self.event_manager:
            return
        try:
            from ..types import EventType
            event_type = getattr(EventType, event_type_name, None)
            if event_type is not None:
                self.event_manager.emit_event(event_type, **kwargs)
        except Exception as e:
            self._log("warning", f"PSR._emit('{event_type_name}') failed: {e}")

    # ------------------------------------------------------------------
    # IProcessStateRegistry
    # ------------------------------------------------------------------

    def register_process(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Зарегистрировать процесс. Если уже есть — обновить. Полезная нагрузка конфига — в initial_state.custom."""
        with self._lock:
            try:
                if process_name in self.states:
                    process_data = self.states[process_name]
                    if initial_state:
                        if "status" in initial_state:
                            raw = initial_state["status"]
                            process_data.status = (
                                raw if isinstance(raw, ProcessStatus)
                                else ProcessStatus(raw)
                            )
                            process_data.update_timestamp()
                        if "metadata" in initial_state:
                            process_data.metadata.update(initial_state["metadata"])
                            process_data.update_timestamp()
                        if "custom" in initial_state:
                            process_data.custom.update(initial_state["custom"])
                            process_data.update_timestamp()
                else:
                    raw_status = (
                        initial_state.get("status", ProcessStatus.INITIALIZING)
                        if initial_state else ProcessStatus.INITIALIZING
                    )
                    status = (
                        raw_status if isinstance(raw_status, ProcessStatus)
                        else ProcessStatus(raw_status)
                    )
                    process_data = ProcessData(
                        name=process_name,
                        status=status,
                        metadata=initial_state.get("metadata", {}) if initial_state else {},
                        custom=initial_state.get("custom", {}) if initial_state else {},
                    )
                    self.states[process_name] = process_data
                    self._emit("PROCESS_REGISTERED", process_name=process_name, state=process_data.to_dict())

                return True
            except Exception as e:
                self._log("error", f"ProcessStateRegistry: register_process('{process_name}') failed: {e}")
                return False

    def has_process(self, process_name: str) -> bool:
        with self._lock:
            return process_name in self.states

    def unregister_process(self, process_name: str) -> bool:
        with self._lock:
            try:
                if process_name in self.states:
                    self._emit("PROCESS_UNREGISTERED", process_name=process_name)
                    del self.states[process_name]
                    return True
                return False
            except Exception as e:
                self._log("error", f"ProcessStateRegistry: unregister_process('{process_name}') failed: {e}")
                return False

    def get_process_data(self, process_name: str) -> Optional[ProcessData]:
        with self._lock:
            return self.states.get(process_name)

    def get_all_process_data(self) -> Dict[str, ProcessData]:
        with self._lock:
            return self.states.copy()

    def get_process_names(self) -> List[str]:
        with self._lock:
            return list(self.states.keys())

    def update_state(
        self,
        process_name: str,
        status: Optional[Any] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        queues: Optional[Dict[str, str]] = None,
        custom: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            try:
                if process_name not in self.states:
                    self.register_process(process_name, {
                        "status": status or ProcessStatus.INITIALIZING,
                        "metadata": metadata or {},
                        "custom": custom or {},
                    })

                process_data = self.states[process_name]
                old_status = process_data.status

                if status is not None:
                    new_status = (
                        status if isinstance(status, ProcessStatus)
                        else ProcessStatus(status)
                    )
                    if old_status != new_status:
                        process_data.status = new_status
                        process_data.update_timestamp()
                        self._emit(
                            "PROCESS_STATE_CHANGED",
                            process_name=process_name,
                            old_status=old_status.value if isinstance(old_status, ProcessStatus) else old_status,
                            new_status=new_status.value,
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
                self._log("error", f"ProcessStateRegistry: update_state('{process_name}') failed: {e}")
                return False

    def add_queue(self, process_name: str, queue_type: str, queue: Queue) -> bool:
        with self._lock:
            try:
                if process_name not in self.states:
                    self.register_process(process_name)
                self.states[process_name].add_queue(queue_type, queue)
                self._emit("QUEUE_ADDED", process_name=process_name, queue_type=queue_type)
                return True
            except Exception as e:
                self._log("error", f"ProcessStateRegistry: add_queue('{process_name}', '{queue_type}') failed: {e}")
                return False

    def add_event(self, process_name: str, event_name: str, event: Event) -> bool:
        with self._lock:
            try:
                if process_name not in self.states:
                    self.register_process(process_name)
                self.states[process_name].add_event(event_name, event)
                self._emit("EVENT_ADDED", process_name=process_name, event_name=event_name)
                return True
            except Exception as e:
                self._log("error", f"ProcessStateRegistry: add_event('{process_name}', '{event_name}') failed: {e}")
                return False

    # ------------------------------------------------------------------
    # Дополнительные методы (обратная совместимость)
    # ------------------------------------------------------------------

    def get_queue(self, process_name: str, queue_type: str) -> Optional[Queue]:
        with self._lock:
            pd = self.states.get(process_name)
            return pd.get_queue(queue_type) if pd else None

    def get_event(self, process_name: str, event_name: str) -> Optional[Event]:
        with self._lock:
            pd = self.states.get(process_name)
            return pd.get_event(event_name) if pd else None

    def get_state(self, process_name: str) -> Optional[ProcessDataDict]:
        with self._lock:
            pd = self.states.get(process_name)
            return pd.to_dict() if pd else None

    def get_all_states(self) -> Dict[str, ProcessDataDict]:
        with self._lock:
            return {name: pd.to_dict() for name, pd in self.states.items()}

    def get_stats(self) -> Dict[str, Any]:
        states = self.get_all_states()
        status_counts: Dict[str, int] = {}
        for state in states.values():
            s = state.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        return {
            "total_processes": len(states),
            "status_counts": status_counts,
            "processes": list(states.keys()),
        }
