# -*- coding: utf-8 -*-
"""
Публичные контракты router_module.

IRouterManager   — единственный интерфейс от которого зависит внешний код.
IMessageChannel  — контракт любого типа канала (Queue, Socket, HTTP, DB, ...).

Правило: внешние модули импортируют только из interfaces.py, не из core/.
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...message_module import Message

from ..channel_routing_module.interfaces import IChannel


class IRouterManager(ABC):
    """Контракт менеджера маршрутизации сообщений."""

    @property
    @abstractmethod
    def manager_name(self) -> str:
        """Имя экземпляра роутера."""

    # ---- Жизненный цикл ----

    @abstractmethod
    def initialize(self) -> bool:
        """Запустить фоновые потоки (AsyncSender). Вернуть True при успехе."""

    @abstractmethod
    def shutdown(self) -> bool:
        """Корректно остановить все потоки, очистить каналы и dispatcher'ы."""

    # ---- Отправка ----

    @abstractmethod
    def send(self, message: Union["Message", Dict[str, Any]]) -> Dict[str, Any]:
        """Синхронная отправка. Блокирует вызывающий поток до завершения.
        Для UI-потоков используй send_async().
        Возвращает {"status": "success"|"error"|"dropped", ...}.
        """

    @abstractmethod
    def send_async(
        self,
        message: Union["Message", Dict[str, Any]],
        priority: str = "normal",
    ) -> None:
        """Non-blocking отправка. Помещает в PriorityQueue AsyncSender'а.
        priority: "urgent" | "high" | "normal" | "low"
        При переполнении буфера — дроп с предупреждением, не исключение.
        """

    # ---- Получение ----

    @abstractmethod
    def receive(
        self,
        timeout: float = 0.0,
        return_messages: bool = True,
    ) -> List[Union["Message", Dict[str, Any]]]:
        """Синхронный опрос всех зарегистрированных каналов.
        timeout=0 → non-blocking.
        return_messages=True → список Message, False → список dict.
        """

    @abstractmethod
    def start_listening(self, poll_interval: float = 0.01) -> bool:
        """Запустить фоновый поток-приёмник.
        Все входящие сообщения передаются зарегистрированным callbacks.
        """

    @abstractmethod
    def stop_listening(self, timeout: float = 5.0) -> bool:
        """Остановить поток-приёмник."""

    @abstractmethod
    def add_message_callback(self, callback: Callable) -> None:
        """Зарегистрировать callback(msg) для входящих сообщений (async receive)."""

    @abstractmethod
    def remove_message_callback(self, callback: Callable) -> None:
        """Удалить callback из списка."""

    # ---- Каналы ----

    @abstractmethod
    def register_channel(self, channel: "IMessageChannel") -> bool:
        """Зарегистрировать канал. При повторной регистрации — замена с предупреждением."""

    @abstractmethod
    def unregister_channel(self, channel_name: str) -> bool:
        """Удалить канал по имени. Вернуть False если не найден."""

    @abstractmethod
    def get_channel(self, channel_name: str) -> Optional["IMessageChannel"]:
        """Получить канал по имени или None."""

    @abstractmethod
    def get_all_channels(self) -> List["IMessageChannel"]:
        """Список всех зарегистрированных каналов."""

    # ---- Маршруты (channel_dispatcher) ----

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
        key: команда/тип сообщения (exact или regex для PATTERN_MATCH).
        channel_name=None → имя канала берётся из msg["channel"] (dynamic).
        strategy=None → EXACT_MATCH.
        """

    @abstractmethod
    def register_broadcast_route(
        self,
        key: str,
        channel_names: List[str],
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Привязать ключ к группе каналов (fan-out / broadcast)."""

    # ---- Обработчики входящих (message_dispatcher) ----

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
        """Зарегистрировать обработчик входящих сообщений.
        Вызывается автоматически во время receive() по ключу command/type.
        """

    # ---- Middleware ----

    @abstractmethod
    def add_send_middleware(self, fn: Callable[[Dict], Optional[Dict]]) -> None:
        """Добавить fn(msg) -> dict|None в pipeline исходящих.
        None → сообщение дропается.
        """

    @abstractmethod
    def add_receive_middleware(self, fn: Callable[[Dict], Optional[Dict]]) -> None:
        """Добавить fn(msg) -> dict|None в pipeline входящих."""

    @abstractmethod
    def clear_middleware(self) -> None:
        """Сбросить все send и receive middleware."""

    # ---- Статистика ----

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Агрегированная статистика роутера, каналов, dispatcher'ов и потоков."""


class IMessageChannel(IChannel):
    """Контракт для любого типа канала сообщений.

    Наследует IChannel — все message-каналы являются IChannel и совместимы
    с ChannelRegistry и ChannelRoutingManager.

    IChannel определяет: name (property), channel_type (property),
    write(data), close(), get_info().

    IMessageChannel добавляет:
      send(message)          — alias для write(), семантика «отправить»
      poll(timeout)          — опрос (pull-модель)
      start/stop_listening() — push-модель (опционально)

    Реализуется для Queue (mp/thread), Socket, HTTP, DB, Log и т.д.
    Каналы stateless относительно маршрутизации — только отправляют/принимают.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя канала (ключ в ChannelRegistry)."""

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Строковый тип: 'queue', 'socket', 'http', 'db', 'log', ..."""

    @abstractmethod
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Отправить сообщение. Вернуть {"status": "success"|"error", ...}."""

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """IChannel.write() — alias для send(). Обеспечивает совместимость с CRM."""
        return self.send(data)

    @abstractmethod
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """Опросить канал. timeout=0 → non-blocking. Вернуть список сообщений."""

    def close(self) -> None:
        """IChannel.close() — останавливает listening если запущен."""
        self.stop_listening()

    def start_listening(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        """Запустить асинхронное прослушивание (push-модель, опционально).
        По умолчанию не поддерживается — RouterManager использует polling.
        """
        return False

    def stop_listening(self) -> bool:
        """Остановить прослушивание."""
        return True

    def get_info(self) -> Dict[str, Any]:
        """Информация о состоянии канала для мониторинга."""
        return {"name": self.name, "type": self.channel_type, "active": True}
