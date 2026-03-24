"""
Публичный контракт queues-подмодуля.

IQueueRegistry — управление очередями: создание, доступ, рассылка.
Использует Any вместо multiprocessing.Queue для pickle-safety.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class IQueueRegistry(ABC):
    """Управление очередями: создание, доступ, рассылка."""

    @abstractmethod
    def create_queues(
        self,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Создать очереди по конфигурации."""

    @abstractmethod
    def create_and_register_queues(
        self,
        process_name: str,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Создать и зарегистрировать очереди для процесса."""

    @abstractmethod
    def register_process_queues(
        self,
        process_name: str,
        queues: Dict[str, Any],
    ) -> bool:
        """Зарегистрировать уже созданные очереди."""

    @abstractmethod
    def get_queue(self, process_name: str, queue_type: str) -> Optional[Any]:
        """Получить очередь процесса."""

    @abstractmethod
    def send_to_queue(
        self,
        process_name: str,
        queue_type: str,
        message: Any,
    ) -> bool:
        """Отправить сообщение в очередь."""

    @abstractmethod
    def broadcast_message(
        self,
        message: Any,
        queue_type: str = "system",
        exclude_process: Optional[str] = None,
    ) -> int:
        """Разослать сообщение всем процессам. Возвращает кол-во доставок."""

    @abstractmethod
    def get_queue_sizes(self) -> Dict[str, Dict[str, int]]:
        """Получить размеры всех очередей."""


__all__ = ["IQueueRegistry"]
