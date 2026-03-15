"""
EventManager — менеджер системных событий.

Использует EventType из types/ (не определяет сам).
Поддерживает reinitialize() для восстановления после unpickle (ADR-020).

Pickle: _event_queue, _subscribers, _new_event_event исключаются.
После unpickle они равны None/{}. reinitialize() пересоздаёт их.
"""

import time
from typing import Any, Callable, Dict, List, Optional
from multiprocessing import Event, Queue

from ....base_manager import BaseManager, ObservableMixin
from ...types import EventType
from ..interfaces import IEventManager
from ...mixins import ManagerStatsMixin


class EventManager(BaseManager, ObservableMixin, IEventManager, ManagerStatsMixin):
    """
    Менеджер системных событий.

    Emit → локальные подписчики + роутер (если подключён).
    Pickle-safe: non-pickle поля исключаются и пересоздаются через reinitialize().
    """

    def __init__(
        self,
        manager_name: str = "EventManager",
        process: Optional[Any] = None,
        router_manager: Optional[Any] = None,
        shared_resources: Optional[Any] = None,
        logger: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        BaseManager.__init__(self, manager_name=manager_name, process=process)

        managers = kwargs.get("managers", {})
        if logger and "logger" not in managers:
            managers["logger"] = logger
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=kwargs.get("config", {}),
            auto_proxy=kwargs.get("auto_proxy", True),
        )

        self._router_manager = router_manager
        self.shared_resources = shared_resources

        # Non-pickle поля (пересоздаются через reinitialize)
        self._event_queue: Optional[Queue] = None
        self._new_event_event: Optional[Event] = None
        self._subscribers: Dict[EventType, List[Callable]] = {}

        self._stats = {"emitted": 0, "subscribed": 0, "notified": 0, "errors": 0}

    # =========================================================================
    # Жизненный цикл
    # =========================================================================

    def initialize(self) -> bool:
        try:
            self._init_event_resources()
            self.is_initialized = True
            self._log_info(f"EventManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"EventManager.initialize() failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self._subscribers.clear()
            self._event_queue = None
            self._new_event_event = None
            self.is_initialized = False
            self._log_info("EventManager shutdown completed")
            return True
        except Exception as e:
            self._log_error(f"EventManager.shutdown() failed: {e}")
            return False

    def reinitialize(self) -> bool:
        """
        Пересоздать non-pickle ресурсы в дочернем процессе (ADR-020).

        Подписки пустые — каждый процесс подписывается заново.
        """
        try:
            self._event_queue = Queue()
            self._new_event_event = Event()
            self._subscribers = {}
            self.is_initialized = True
            return True
        except Exception as e:
            self._log_error(f"EventManager.reinitialize() failed: {e}")
            return False

    def _init_event_resources(self) -> None:
        self._event_queue = Queue()
        self._new_event_event = Event()

    # =========================================================================
    # IEventManager
    # =========================================================================

    def emit_event(
        self,
        event_type: EventType,
        process_name: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        self._stats["emitted"] += 1
        try:
            event_data = {
                "type": "system_event",
                "event_type": event_type.value,
                "process_name": process_name,
                "timestamp": time.time(),
                **kwargs,
            }

            if self._router_manager:
                try:
                    ch = getattr(self._router_manager, "get_channel", None)
                    if ch and ch("system_events"):
                        self._router_manager.send({
                            "type": "system_event",
                            "command": "system_event",
                            "channel": "system_events",
                            "sender": "EventManager",
                            "content": event_data,
                            "targets": ["ProcessManager"],
                        })
                except Exception as e:
                    self._log_error(f"Failed to send event via router: {e}")
                    self._stats["errors"] += 1

            if self._event_queue is not None:
                self._event_queue.put(event_data)
                if self._new_event_event is not None:
                    self._new_event_event.set()

            self._notify_subscribers(event_type, event_data)
            return True
        except Exception as e:
            self._log_error(f"emit_event({event_type}) failed: {e}")
            self._stats["errors"] += 1
            return False

    def subscribe(self, event_type: EventType, callback: Callable) -> bool:
        self._subscribers.setdefault(event_type, []).append(callback)
        self._stats["subscribed"] += 1
        return True

    def unsubscribe(self, event_type: EventType, callback: Callable) -> bool:
        callbacks = self._subscribers.get(event_type, [])
        if callback in callbacks:
            callbacks.remove(callback)
            return True
        return False

    def wait_for_event(
        self,
        event_type: Optional[EventType] = None,
        timeout: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        if self._new_event_event is None or self._event_queue is None:
            return None

        start = time.time()
        while time.time() - start < timeout:
            if self._new_event_event.wait(timeout=0.1):
                try:
                    event_data = self._event_queue.get(timeout=0.1)
                    if event_type is None or event_data.get("event_type") == event_type.value:
                        return event_data
                    self._event_queue.put(event_data)
                except Exception:
                    pass
                self._new_event_event.clear()
        return None

    # =========================================================================
    # Вспомогательное
    # =========================================================================

    def _notify_subscribers(self, event_type: EventType, event_data: Dict[str, Any]) -> None:
        for callback in self._subscribers.get(event_type, []):
            try:
                callback(event_data)
                self._stats["notified"] += 1
            except Exception as e:
                self._log_error(f"Subscriber callback error: {e}")
                self._stats["errors"] += 1

    def set_router_manager(self, router_manager: Any) -> None:
        self._router_manager = router_manager

    @property
    def router_manager(self) -> Optional[Any]:
        return self._router_manager

    def get_event_queue(self) -> Optional[Queue]:
        return self._event_queue

    def get_new_event_event(self) -> Optional[Event]:
        return self._new_event_event

    def get_stats(self) -> Dict[str, Any]:
        event_stats = {
            **self._stats,
            "subscribers_count": sum(len(v) for v in self._subscribers.values()),
            "event_types": [et.value for et in self._subscribers],
        }
        return self._merge_stats("events", event_stats)

    # =========================================================================
    # Pickle
    # =========================================================================

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        _EXCLUDE = (
            "log_debug", "log_info", "log_warning", "log_error", "log_critical",
            "record_metric", "increment", "record_timing", "gauge",
            "track_error", "record_error",
            "_call_manager", "_registry", "_plugin_registry", "_proxy_created",
            "_event_queue", "_subscribers", "_new_event_event",
        )
        for key in _EXCLUDE:
            state.pop(key, None)
        state.setdefault("_adapters", {})
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._event_queue = None
        self._new_event_event = None
        self._subscribers = {}
