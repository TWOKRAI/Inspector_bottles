# -*- coding: utf-8 -*-
"""
Интерфейсы router_module.

IRouterManager — контракт для любой реализации роутера.
IMessageChannel — контракт для любого типа канала (Queue, Socket, HTTP, ...).
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...message_module import Message


class IRouterManager(ABC):
    """Контракт для менеджера маршрутизации."""

    @property
    @abstractmethod
    def manager_name(self) -> str:
        """Имя роутера."""

    @abstractmethod
    def initialize(self) -> bool:
        """Инициализация (запуск фоновых потоков, регистрация каналов)."""

    @abstractmethod
    def shutdown(self) -> bool:
        """Корректная остановка всех потоков и очистка ресурсов."""

    # --- Отправка ---

    @abstractmethod
    def send(self, message: Union["Message", Dict[str, Any]]) -> Dict[str, Any]:
        """Синхронная отправка. Может блокироваться."""

    @abstractmethod
    def send_async(
        self,
        message: Union["Message", Dict[str, Any]],
        priority: str = "normal",
    ) -> None:
        """Non-blocking отправка. Безопасна для UI-потока."""

    # --- Получение ---

    @abstractmethod
    def receive(
        self,
        timeout: float = 0.0,
        return_messages: bool = True,
    ) -> List[Union["Message", Dict[str, Any]]]:
        """Синхронный опрос всех каналов."""

    @abstractmethod
    def start_listening(self, poll_interval: float = 0.01) -> bool:
        """Запустить фоновый поток приёма сообщений."""

    @abstractmethod
    def stop_listening(self, timeout: float = 5.0) -> bool:
        """Остановить фоновый поток приёма."""

    @abstractmethod
    def add_message_callback(self, callback: Callable) -> None:
        """Зарегистрировать callback для входящих сообщений."""

    # --- Каналы ---

    @abstractmethod
    def register_channel(self, channel: "IMessageChannel") -> bool:
        """Зарегистрировать канал."""

    @abstractmethod
    def unregister_channel(self, channel_name: str) -> bool:
        """Удалить канал."""

    @abstractmethod
    def get_channel(self, channel_name: str) -> Optional["IMessageChannel"]:
        """Получить канал по имени."""

    # --- Маршрутизация (channel_dispatcher) ---

    @abstractmethod
    def register_route(
        self,
        key: str,
        channel_name: Optional[str],
        strategy: Any = None,
        efficiency: int = 0,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Привязать routing-ключ к каналу через channel_dispatcher.
        strategy=None → EXACT_MATCH.
        channel_name=None → брать из msg['channel'] (dynamic).
        """

    @abstractmethod
    def register_broadcast_route(
        self,
        key: str,
        channel_names: List[str],
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Привязать ключ к группе каналов (fan-out)."""

    # --- Обработчики входящих ---

    @abstractmethod
    def register_message_handler(
        self,
        key: str,
        handler: Callable,
        expects_full_message: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        efficiency: int = 0,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Зарегистрировать обработчик входящих сообщений."""

    # --- Middleware ---

    @abstractmethod
    def add_send_middleware(self, fn: Callable) -> None:
        """Добавить middleware для исходящих сообщений."""

    @abstractmethod
    def add_receive_middleware(self, fn: Callable) -> None:
        """Добавить middleware для входящих сообщений."""

    # --- Статистика ---

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Полная статистика роутера."""


class IMessageChannel(ABC):
    """Контракт для любого типа канала сообщений.

    Реализуется для Queue (mp/thread), Socket, HTTP, Database, Log и т.д.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя канала."""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Тип канала: 'queue', 'socket', 'http', 'log', ...)."""

    @abstractmethod
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить сообщение. Возвращает {"status": "success"|"error", ...}."""

    @abstractmethod
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Опросить канал. timeout=0 → non-blocking."""

    def start_listening(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        """Запустить асинхронное прослушивание (опционально)."""
        return False

    def stop_listening(self) -> bool:
        """Остановить прослушивание."""
        return True

    def get_info(self) -> Dict[str, Any]:
        """Информация о состоянии канала."""
        return {"name": self.name, "type": self.channel_type, "active": True}
