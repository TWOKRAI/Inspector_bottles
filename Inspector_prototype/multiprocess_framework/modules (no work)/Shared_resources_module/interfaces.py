"""
Интерфейсы для Shared Resources Module.

Определяет публичный API для всех компонентов модуля.
Упрощает тестирование и расширение функциональности.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from multiprocessing import Queue, Event
from pathlib import Path


class IQueueManager(ABC):
    """Интерфейс для менеджера очередей."""
    
    @abstractmethod
    def create_queues(
        self,
        queue_config: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Queue]:
        """Создать очереди на основе конфигурации."""
        pass
    
    @abstractmethod
    def register_process_queues(
        self,
        process_name: str,
        queues: Dict[str, Queue]
    ) -> bool:
        """Зарегистрировать очереди процесса."""
        pass
    
    @abstractmethod
    def get_queue(
        self,
        process_name: str,
        queue_type: str
    ) -> Optional[Queue]:
        """Получить очередь процесса."""
        pass
    
    @abstractmethod
    def get_process_queues(self, process_name: str) -> Dict[str, Queue]:
        """Получить все очереди процесса."""
        pass
    
    @abstractmethod
    def send_to_queue(
        self,
        process_name: str,
        queue_type: str,
        data: Any
    ) -> bool:
        """Отправить данные в очередь."""
        pass


class IEventManager(ABC):
    """Интерфейс для менеджера событий."""
    
    @abstractmethod
    def emit_event(
        self,
        event_type: Any,
        process_name: Optional[str] = None,
        **kwargs
    ) -> bool:
        """Отправить событие."""
        pass
    
    @abstractmethod
    def subscribe(
        self,
        event_type: Any,
        callback: Any
    ) -> bool:
        """Подписаться на события."""
        pass
    
    @abstractmethod
    def wait_for_event(
        self,
        event_type: Optional[Any] = None,
        timeout: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """Ожидать событие с таймаутом."""
        pass


class IMemoryManager(ABC):
    """Интерфейс для менеджера разделяемой памяти."""
    
    @abstractmethod
    def create_memory_dict(
        self,
        process_name: str,
        memory_names: Dict[str, tuple],
        coll: int
    ) -> bool:
        """Создать память для процесса."""
        pass
    
    @abstractmethod
    def get_memory_data(
        self,
        process_name: str,
        memory_name: str
    ) -> Optional[Dict]:
        """Получить данные памяти."""
        pass
    
    @abstractmethod
    def write_images(
        self,
        process_name: str,
        memory_name: str,
        images: Any,
        index: int = 0
    ) -> bool:
        """Записать изображения в память."""
        pass
    
    @abstractmethod
    def read_images(
        self,
        process_name: str,
        memory_name: str,
        index: int = 0
    ) -> Optional[Any]:
        """Прочитать изображения из памяти."""
        pass


class IProcessStateRegistry(ABC):
    """Интерфейс для реестра состояний процессов."""
    
    @abstractmethod
    def register_process(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        config: Optional[Any] = None
    ) -> bool:
        """Зарегистрировать процесс."""
        pass
    
    @abstractmethod
    def get_process_data(self, process_name: str) -> Optional[Any]:
        """Получить ProcessData процесса."""
        pass
    
    @abstractmethod
    def get_all_process_data(self) -> Dict[str, Any]:
        """Получить все ProcessData."""
        pass
    
    @abstractmethod
    def update_state(
        self,
        process_name: str,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Обновить состояние процесса."""
        pass
    
    @abstractmethod
    def add_queue(
        self,
        process_name: str,
        queue_type: str,
        queue: Queue
    ) -> bool:
        """Добавить очередь в процесс."""
        pass
    
    @abstractmethod
    def add_event(
        self,
        process_name: str,
        event_name: str,
        event: Event
    ) -> bool:
        """Добавить событие в процесс."""
        pass


class ISharedResourcesManager(ABC):
    """Интерфейс для главного менеджера ресурсов."""
    
    @abstractmethod
    def get_process_data(self, process_name: str) -> Optional[Any]:
        """Получить ProcessData процесса."""
        pass
    
    @abstractmethod
    def get_all_process_data(self) -> Dict[str, Any]:
        """Получить все ProcessData."""
        pass
    
    @abstractmethod
    def register_process_state(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Зарегистрировать состояние процесса."""
        pass
    
    @property
    def process_state_registry(self) -> IProcessStateRegistry:
        """Получить реестр процессов."""
        pass
    
    @property
    def event_manager(self) -> IEventManager:
        """Получить менеджер событий."""
        pass

