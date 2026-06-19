# -*- coding: utf-8 -*-
"""
event_module/interfaces.py — Protocol-контракты EventBus и подписок (generic).

EventBusProtocol — контракт typed pub/sub.
Subscription     — контракт управления подпиской (unsubscribe + context manager).

Разделение контракт/реализация позволяет потребителям зависеть от протокола без
импорта конкретной шины, а приложению — обернуть EventBus в Qt-thread-safe вариант
(QtEventBus) без смены контракта.

Generic: тип события не ограничен (шина диспетчеризует по type(event)).
Carve-out 2026-06-18 из multiprocess_prototype/domain/protocols/event_bus.py.
"""

from __future__ import annotations

from typing import Callable, Protocol, TypeVar

E = TypeVar("E")


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
    """Контракт typed pub/sub шины событий.

    Реализации: EventBus (event_module/event_bus.py), QtEventBus (frontend-обёртка),
    fake-шины в тестах.

    subscribe принимает конкретный тип события (не union) — это обеспечивает корректное
    type-narrowing в handler'ах.
    """

    def publish(self, event: object) -> None:
        """Опубликовать событие всем подписчикам на его тип."""
        ...

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
    ) -> Subscription:
        """Подписаться на события конкретного типа. Возвращает Subscription."""
        ...


__all__ = [
    "Subscription",
    "EventBusProtocol",
]
