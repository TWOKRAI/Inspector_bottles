# -*- coding: utf-8 -*-
"""interfaces.py — Protocol-контракты backend_ctl (правило проекта №2).

Структурные контракты (PEP 544 :class:`typing.Protocol`) для трёх ролей driver'а.
Не наследуются — служат явной документацией контракта и точкой типизации для
потребителей (MCP-сервер, harness), устойчивой к распилу ``driver.py`` (Phase C):
реализация может переехать между модулями, контракт остаётся здесь.

  * :class:`ISubscriptionRegistry` — реестр durable-намерений (``subscriptions.py``);
  * :class:`IEventSource` — событийный канал push-сообщений (``events`` внутри driver);
  * :class:`IBackendClient` — ядро TCP-клиента: соединение + request-response +
    команды + durable-подписки (``BackendDriver``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

EventCallback = Any  # Callable[[Dict[str, Any]], None] — избегаем циклов импорта


@runtime_checkable
class ISubscriptionRegistry(Protocol):
    """Реестр durable-намерений подписки: пережить реконнект без молчаливой потери."""

    def add(self, command: str, target: str, args: Dict[str, Any]) -> None: ...

    def remove(self, command: str, target: str, args: Optional[Dict[str, Any]] = None) -> None: ...

    def remove_by_command(self, command: str) -> None: ...

    def export(self) -> List[Dict[str, Any]]: ...

    def load(self, intents: List[Dict[str, Any]]) -> None: ...


@runtime_checkable
class IEventSource(Protocol):
    """Событийный канал: push-сообщения без reply (state.changed / observability.record).

    ``events_page`` — курсорное недеструктивное чтение по плоскостям (B.1);
    ``events`` — устаревший деструктивный дренаж (удаление обёртки — F.1).
    """

    def subscribe(self, callback: EventCallback) -> EventCallback: ...

    def unsubscribe(self, callback: EventCallback) -> None: ...

    def events(
        self,
        timeout: Optional[float] = 0.0,
        *,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]: ...

    def events_page(
        self,
        plane: Optional[str] = None,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]: ...


@runtime_checkable
class IBackendClient(Protocol):
    """Ядро driver'а: соединение + request-response + команды + durable-подписки.

    Контракт, на который опираются потребители (MCP-сервер через DriverSession,
    harness). Не перечисляет все доменные обёртки — только несущий каркас клиента.
    """

    def connect(self, timeout: float = 5.0) -> None: ...

    def close(self) -> None: ...

    def request(self, message: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]: ...

    def send_command(
        self,
        target: str,
        command: str,
        args: Optional[Dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]: ...

    def export_subscriptions(self) -> List[Dict[str, Any]]: ...

    def import_subscriptions(self, intents: List[Dict[str, Any]]) -> None: ...

    def replay_subscriptions(self) -> List[Dict[str, Any]]: ...


__all__ = ["ISubscriptionRegistry", "IEventSource", "IBackendClient"]
