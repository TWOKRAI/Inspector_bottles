# -*- coding: utf-8 -*-
"""
frontend/qt_event_bus.py — Qt-aware обёртка над domain.EventBus (Task D.2).

QtEventBus:
  - publish() из main thread — синхронный pass-through к внутреннему EventBus.
  - publish() из любого другого thread'а — маршалит вызов на main thread через
    внутренний Signal(object) с QueuedConnection (автоматически при cross-thread emit).
  - subscribe() — pass-through к внутреннему EventBus.
  - Удовлетворяет domain.protocols.EventBusProtocol.

Мотивация (Phase D, закрытый Q1): domain остаётся UI-agnostic; Qt-specific
thread-safety вынесена в frontend/ как wrapper, не изменяя pure Python EventBus.

Примечание по реализации маршалинга:
  QMetaObject.invokeMethod + Q_ARG(object, ...) в PySide6 6.10 не поддерживает
  Python-объекты без зарегистрированного QMetaType. Вместо этого используется
  Signal(object) — PySide6 корректно marshal'ит emit() через QueuedConnection,
  когда emit вызывается из thread'а, отличного от receiver-thread QObject'а.

Stability: lite
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import (
    QObject,
    QThread,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtWidgets import QApplication

from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import ProjectEvent
from multiprocess_prototype.domain.protocols.event_bus import Subscription

_logger = logging.getLogger(__name__)


def _is_main_thread() -> bool:
    """Проверить, выполняется ли текущий код в main thread приложения Qt.

    Возвращает True если:
      - QApplication.instance() is None (нет Qt-приложения; тест вне Qt-loop),
      - или QThread.currentThread() совпадает с потоком QApplication.

    Возвращает False только при наличии живого QApplication И текущий поток
    отличается от потока QApplication.
    """
    app = QApplication.instance()
    if app is None:
        # Нет Qt-приложения — считаем, что мы на main thread (для unit-тестов).
        return True
    return QThread.currentThread() is app.thread()


class QtEventBus(QObject):
    """Qt-aware обёртка над domain.EventBus.

    publish() из любого thread'а маршалится на main thread через внутренний
    Signal(object). При cross-thread emit() Qt автоматически устанавливает
    QueuedConnection, доставляя событие через event-loop на thread QObject'а.
    subscribe — pass-through к внутреннему EventBus.

    Удовлетворяет domain.protocols.EventBusProtocol.

    Pre:
      parent: опциональный QObject-родитель (стандартная семантика Qt ownership).

    Post:
      subscribe(event_type, handler) -> Subscription (не None).
      publish(event): если main thread — синхронный вызов handler'ов.
                      если worker thread — delivery через QueuedConnection
                      (async, на main thread, до следующей итерации event-loop'а).

    Invariants:
      Внутренний EventBus не имеет Qt-зависимостей (domain чистый).
      Все ошибки subscriber'ов логируются через logging, не поглощаются.
    """

    # Внутренний сигнал для маршалинга с worker thread на main thread.
    # Signal(object) в PySide6 поддерживает любые Python-объекты.
    # При emit() из другого thread'а — Qt автоматически выбирает QueuedConnection.
    _worker_event = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Инициализируем внутренний bus с кастомным error_handler для логирования
        self._bus = EventBus(error_handler=self._on_error)
        # Подключаем сигнал к слоту: соединение AutoConnection позволяет Qt
        # выбрать QueuedConnection при cross-thread и DirectConnection на same thread.
        self._worker_event.connect(
            self._dispatch_on_main,
            Qt.ConnectionType.QueuedConnection,
        )

    # ------------------------------------------------------------------
    # Публичный API (EventBusProtocol)
    # ------------------------------------------------------------------

    def publish(self, event: ProjectEvent) -> None:
        """Опубликовать событие.

        Если вызов идёт из main thread — синхронная доставка (pass-through).
        Если из worker thread — emit через Signal(object), Qt доставит
        на main thread через QueuedConnection (event-loop итерация).
        """
        if _is_main_thread():
            self._bus.publish(event)
        else:
            self._worker_event.emit(event)

    def subscribe(
        self,
        event_type: type,
        handler: Callable,
    ) -> Subscription:
        """Подписаться на событие конкретного типа.

        Pass-through к внутреннему domain.EventBus.subscribe().
        Возвращает Subscription с unsubscribe() и поддержкой context manager.
        """
        return self._bus.subscribe(event_type, handler)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Слот для приёма маршалированных событий из worker thread
    # ------------------------------------------------------------------

    @Slot(object)
    def _dispatch_on_main(self, event: object) -> None:
        """Вызывается на main thread через QueuedConnection от _worker_event.

        Выполняет реальный publish на внутреннем EventBus уже на main thread.
        """
        # Аннотация event: object для совместимости с Slot(object);
        # фактически принимает ProjectEvent (union frozen dataclasses).
        self._bus.publish(event)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Error handler для внутреннего EventBus
    # ------------------------------------------------------------------

    def _on_error(self, exc: Exception, event: ProjectEvent) -> None:
        """Логировать ошибку subscriber'а через стандартный logging.

        Не поглощает исключение молча — соответствует правилу 5 CLAUDE.md.
        """
        _logger.exception(
            "QtEventBus: subscriber raised for event %r: %s",
            event,
            exc,
        )


__all__ = ["QtEventBus"]
