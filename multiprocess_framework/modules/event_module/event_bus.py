# -*- coding: utf-8 -*-
"""
event_module/event_bus.py — pure Python synchronous typed pub/sub (generic).

EventBus:
  - subscribe(event_type, handler) -> _Subscription (context-manager)
  - publish(event) — snapshot handler'ов под lock, вызов без lock
  - default error_handler = logging.exception (правило 5 CLAUDE.md — не silent)
  - thread-safety: RLock для subscribe/unsubscribe/publish

Generic: событие непрозрачно для шины (диспетчеризация только по ``type(event)``), поэтому
тип события НЕ ограничен — шина переиспользуется любым приложением с любым набором событий
(прототип публикует свой ``ProjectEvent``-union, но шина об этом не знает). Никаких Qt- и
app-зависимостей: Qt thread-safety обеспечивает обёртка на стороне приложения (QtEventBus).

Carve-out 2026-06-18 из multiprocess_prototype/domain/event_bus.py (правило framework-first).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import RLock
from types import TracebackType
from typing import Any, Generic, TypeVar

_logger = logging.getLogger(__name__)

E = TypeVar("E")

# Тип пользовательского error-handler'а: (exception, event) -> None.
# event типизирован как Any — шина не ограничивает тип события.
ErrorHandler = Callable[[Exception, Any], None]


class _Subscription(Generic[E]):
    """Управление подпиской: context-manager + explicit unsubscribe.

    При __exit__ или unsubscribe() удаляет handler из списка bus.
    Повторный unsubscribe — no-op (идемпотентный).
    """

    def __init__(
        self,
        bus: "EventBus",
        event_type: type[E],
        handler: Callable[[E], None],
    ) -> None:
        self._bus = bus
        self._event_type = event_type
        self._handler: Callable[[E], None] | None = handler

    def unsubscribe(self) -> None:
        """Отменить подписку. Повторный вызов — no-op."""
        if self._handler is None:
            return
        handler = self._handler
        self._handler = None
        with self._bus._lock:
            bucket = self._bus._handlers.get(self._event_type)
            if bucket is not None:
                try:
                    bucket.remove(handler)  # type: ignore[arg-type]
                except ValueError:
                    pass  # Уже удалён (race-free благодаря RLock)

    def __enter__(self) -> "_Subscription[E]":
        """Возвращает self для использования в with-блоке."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Автоматически отменяет подписку при выходе из with-блока."""
        self.unsubscribe()


class EventBus:
    """Pure Python synchronous typed pub/sub (generic по типу события).

    Pre:
      error_handler: Optional callback (Exception, event) -> None.
      По умолчанию logging.exception() — никаких silent swallows (правило 5 CLAUDE.md).

    Post:
      subscribe(event_type, handler) -> _Subscription. Не возвращает None.
      publish(event) — синхронно вызывает все handler'ы, зарегистрированные
      под type(event). Исключение в одном handler не прерывает остальных.

    Invariants:
      - subscribe к одному event_type: handler'ы вызываются в порядке регистрации.
      - publish для типа без subscriber'ов — no-op без ошибок.
      - thread-safety: внутренний RLock на subscribe/unsubscribe/publish.
        unsubscribe внутри handler работает корректно: publish snapshot-ирует
        список до вызовов (не держит lock во время вызовов).
    """

    def __init__(self, error_handler: ErrorHandler | None = None) -> None:
        # dict[type, list[Callable]] — хранит handler'ы по типу события
        self._handlers: dict[type, list[Callable[..., None]]] = {}
        self._lock = RLock()
        self._error_handler = error_handler

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
    ) -> _Subscription[E]:
        """Подписаться на события конкретного типа.

        Handler'ы вызываются в порядке регистрации.
        Возвращает _Subscription — context-manager для auto-unsubscribe.
        """
        with self._lock:
            bucket = self._handlers.setdefault(event_type, [])
            bucket.append(handler)  # type: ignore[arg-type]
        return _Subscription(self, event_type, handler)

    def publish(self, event: object) -> None:
        """Опубликовать событие всем подписчикам на его конкретный тип.

        Алгоритм:
          1. Под lock — сделать snapshot списка handler'ов для type(event).
          2. Без lock — вызвать каждый handler поочерёдно.
          3. Исключение в handler N: вызвать error_handler (или logger.exception),
             продолжить с handler N+1.

        publish для типа без подписчиков — no-op без ошибок.
        """
        event_type = type(event)
        # Snapshot под lock — защита от concurrent subscribe/unsubscribe
        with self._lock:
            bucket = self._handlers.get(event_type)
            handlers_snapshot = list(bucket) if bucket else []

        # Вызываем handler'ы без lock — RLock позволяет reentrant subscribe/unsubscribe
        for handler in handlers_snapshot:
            try:
                handler(event)
            except Exception as exc:
                if self._error_handler is not None:
                    try:
                        self._error_handler(exc, event)
                    except Exception:
                        # Защита от ошибок в самом error_handler — log и идём дальше
                        _logger.exception("EventBus: error_handler raised for event %r", event)
                else:
                    _logger.exception("EventBus: handler %r raised for event %r", handler, event)


__all__ = [
    "EventBus",
    "ErrorHandler",
]
