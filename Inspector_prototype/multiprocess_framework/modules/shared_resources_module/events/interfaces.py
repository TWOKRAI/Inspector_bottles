"""
Публичный контракт events-подмодуля.

IEventManager — системные события: emit, subscribe, wait, reinitialize.
Использует Any для event_type — pickle-safety.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional


class IEventManager(ABC):
    """Системные события: emit, subscribe, wait, reinitialize."""

    @abstractmethod
    def emit_event(
        self,
        event_type: Any,
        process_name: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Отправить событие."""

    @abstractmethod
    def subscribe(self, event_type: Any, callback: Callable) -> bool:
        """Подписаться на события."""

    @abstractmethod
    def wait_for_event(
        self,
        event_type: Optional[Any] = None,
        timeout: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        """Ожидать событие с таймаутом."""

    @abstractmethod
    def reinitialize(self) -> bool:
        """Пересоздать non-pickle ресурсы после unpickle в дочернем процессе."""


__all__ = ["IEventManager"]
