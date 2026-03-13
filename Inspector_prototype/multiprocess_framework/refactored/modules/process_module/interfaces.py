# -*- coding: utf-8 -*-
"""
Публичные контракты process_module.

Единственный файл, от которого должны зависеть внешние модули.
Внутренние компоненты используют относительные импорты.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .types import ProcessStatus, ProcessConfigDict, ProcessStatsDict


class IProcessModule(ABC):
    """
    Контракт базового процесса системы.

    Реализуется ProcessModule. Внешние модули (process_manager_module, adapters)
    должны зависеть только от этого интерфейса.

    Жизненный цикл: initialize() -> run() -> stop() -> shutdown()
    """

    # ---- Жизненный цикл ----

    @abstractmethod
    def initialize(self) -> bool: ...

    @abstractmethod
    def shutdown(self) -> bool: ...

    @abstractmethod
    def run(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def should_stop(self) -> bool: ...

    # ---- Коммуникация ----

    @abstractmethod
    def send_message(self, target: str, message: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def broadcast_message(self, message: Dict[str, Any], exclude_self: bool = True) -> bool: ...

    @abstractmethod
    def receive_message(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]: ...

    # ---- Конфигурация ----

    @abstractmethod
    def get_config(self, key: str, default: Any = None) -> Any: ...

    @abstractmethod
    def update_config(self, key: str, value: Any) -> None: ...

    # ---- Состояние ----

    @abstractmethod
    def update_process_state(
        self,
        status: Optional[str] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    # ---- Статистика ----

    @abstractmethod
    def get_stats(self) -> ProcessStatsDict: ...


class ISharedResources:
    """
    Protocol-контракт для shared_resources_module.

    process_module НЕ импортирует SharedResourcesManager напрямую.
    Вместо этого он работает через этот protocol, получая зависимость через DI.

    Это разрывает циклическую зависимость:
        process_module -> shared_resources_module (было)
        process_module -> ISharedResources (стало — только protocol)
    """

    def get_process_data(self, name: str) -> Optional[Dict[str, Any]]:
        """Получить данные процесса по имени."""
        ...

    def register_process_state(
        self,
        process_name: str,
        initial_state: Optional[Dict[str, Any]] = None,
        queue_names: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Зарегистрировать состояние процесса."""
        ...

    def update_process_state(
        self,
        process_name: str,
        status: Optional[str] = None,
        events: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        custom: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Обновить состояние процесса."""
        ...

    @property
    def queue_registry(self) -> Any:
        """Реестр очередей."""
        ...

    @property
    def memory_manager(self) -> Any:
        """Менеджер памяти."""
        ...

    @property
    def event_manager(self) -> Any:
        """Менеджер событий."""
        ...

    @property
    def process_state_registry(self) -> Any:
        """Реестр состояний процессов."""
        ...


class IProcessCommunication:
    """
    Protocol-контракт для ProcessCommunication.

    Определяет публичный API для межпроцессной коммуникации.
    """

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить сообщение через роутер."""
        ...

    def receive(self, timeout: float = 0.01) -> List[Dict[str, Any]]:
        """Получить входящие сообщения."""
        ...

    def send_to_process(self, target: str, message: Dict[str, Any]) -> bool:
        """Отправить сообщение конкретному процессу."""
        ...

    def broadcast(self, message: Dict[str, Any], exclude_self: bool = True) -> int:
        """Разослать сообщение всем процессам."""
        ...

    def send_message(self, target: str, message: Dict[str, Any]) -> bool:
        """Псевдоним send_to_process для совместимости."""
        ...

    def broadcast_message(self, message: Dict[str, Any], exclude_self: bool = True) -> bool:
        """Псевдоним broadcast для совместимости."""
        ...

    def receive_message(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Получить одно сообщение."""
        ...

    def register_process_queues(self) -> None:
        """Зарегистрировать очереди процесса в queue_registry."""
        ...

    def register_router_channels(self) -> None:
        """Зарегистрировать каналы в роутере."""
        ...

    def unregister_process(self) -> None:
        """Отменить регистрацию процесса."""
        ...

    def get_queue_stats(self) -> Dict[str, Any]:
        """Получить статистику очередей."""
        ...
