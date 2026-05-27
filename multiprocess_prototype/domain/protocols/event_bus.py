# -*- coding: utf-8 -*-
"""
domain/protocols/event_bus.py — Protocol для EventBus и подписок.

EventBusProtocol — контракт для typed pub/sub.
Subscription       — контракт для управления подпиской (unsubscribe + context manager).

Это ТОЛЬКО Protocol-файл. Реальная реализация EventBus (pure Python,
synchronous) создаётся в Task B.6 в domain/event_bus.py.

Разделение позволяет:
  - Protocols использоваться в AppServices без зависимости на impl.
  - В Phase D обернуть EventBus в Qt-thread-safe вариант без смены Protocol.
"""

from __future__ import annotations

from typing import Callable, Protocol, TypeVar

from ..events import ProjectEvent

E = TypeVar("E", bound=ProjectEvent)


class Subscription(Protocol):
    """Контракт управления подпиской на EventBus.

    Поддерживает явный unsubscribe() и использование как context manager.
    """

    def unsubscribe(self) -> None:
        """Отменить подписку. Повторный вызов — no-op."""
        ...

    def __enter__(self) -> "Subscription":
        """Вернуть self для использования в with-блоке."""
        ...

    def __exit__(self, *exc_info: object) -> None:
        """Автоматически вызывает unsubscribe() при выходе из with-блока."""
        ...


class EventBusProtocol(Protocol):
    """Контракт для typed pub/sub шины событий.

    Реализации: EventBus в domain/event_bus.py (Task B.6), _FakeEventBus (тесты).

    Примечание: subscribe принимает конкретный тип события (не union),
    что обеспечивает корректное type-narrowing в handler'ах.
    """

    def publish(self, event: ProjectEvent) -> None:
        """Опубликовать событие всем подписчикам на его тип."""
        ...

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
    ) -> Subscription:
        """Подписаться на события конкретного типа.

        Возвращает Subscription для управления подпиской.
        """
        ...


__all__ = [
    "Subscription",
    "EventBusProtocol",
]
