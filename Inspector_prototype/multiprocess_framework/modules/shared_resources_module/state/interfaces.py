"""
Публичный контракт state-подмодуля.

IProcessStateRegistry — реестр runtime-состояний процессов (Dict[str, ProcessData]).
Использует Any для Queue/Event — pickle-safety, отсутствие тяжёлых зависимостей.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class IProcessStateRegistry(ABC):
    """Реестр runtime-состояний процессов: Dict[str, ProcessData]."""

    @abstractmethod
    def register_process(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        config: Optional[Any] = None,
    ) -> bool:
        """Зарегистрировать процесс."""

    @abstractmethod
    def has_process(self, process_name: str) -> bool:
        """Проверить наличие процесса."""

    @abstractmethod
    def unregister_process(self, process_name: str) -> bool:
        """Удалить процесс из реестра."""

    @abstractmethod
    def get_process_data(self, process_name: str) -> Optional[Any]:
        """Получить ProcessData процесса."""

    @abstractmethod
    def get_all_process_data(self) -> Dict[str, Any]:
        """Получить все ProcessData."""

    @abstractmethod
    def get_process_names(self) -> List[str]:
        """Список всех зарегистрированных процессов."""

    @abstractmethod
    def update_state(
        self,
        process_name: str,
        status: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Обновить состояние процесса."""

    @abstractmethod
    def add_queue(
        self,
        process_name: str,
        queue_type: str,
        queue: Any,
    ) -> bool:
        """Добавить очередь в ProcessData процесса."""

    @abstractmethod
    def add_event(
        self,
        process_name: str,
        event_name: str,
        event: Any,
    ) -> bool:
        """Добавить событие в ProcessData процесса."""


__all__ = ["IProcessStateRegistry"]
