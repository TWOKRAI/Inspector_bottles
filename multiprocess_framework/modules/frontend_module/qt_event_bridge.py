# -*- coding: utf-8 -*-
"""
frontend_module/qt_event_bridge.py — Qt-aware мост над event_module.EventBus (E2/Task 5.5).

Purpose:
    Механизм cross-thread маршалинга событий на main thread Qt (уровень 1,
    UI-toolkit). App-agnostic: не завязан на конкретный тип события.

Public API:
    ``QtEventBus`` — Qt-обёртка (``publish``/``subscribe``), удовлетворяет
    ``event_module.EventBusProtocol``.

``QtEventBus`` — механизм cross-thread маршалинга событий на main thread Qt.
Ранее жил в ``multiprocess_prototype/frontend/qt_event_bus.py`` и был привязан к
прототип-типам (``domain.EventBus``/``ProjectEvent``/``Subscription``). При выносе
во framework привязки сняты:

  - ``EventBus``/``Subscription``/``ErrorHandler`` — уже во framework
    (``event_module``), берём напрямую (framework-internal);
  - **type-bound → generic**: события трактуются как непрозрачный ``object`` —
    мост маршалит и форвардит любой тип события, не завися от прототип-union
    ``ProjectEvent``. Судьба ``EventBusProtocol`` уже решена (в ``event_module``);
    ``QtEventBus`` удовлетворяет ему структурно, без реэкспорта.

Мотивация (Phase D, закрытый Q1): domain/приложение остаётся UI-agnostic; Qt-specific
thread-safety — это механизм уровня 1, живёт в UI-toolkit слое framework
(``frontend_module``), не изменяя pure-Python ``EventBus``.

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

from multiprocess_framework.modules.event_module import EventBus, Subscription

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
    """Qt-aware обёртка над ``event_module.EventBus``.

    publish() из любого thread'а маршалится на main thread через внутренний
    Signal(object). При cross-thread emit() Qt автоматически устанавливает
    QueuedConnection, доставляя событие через event-loop на thread QObject'а.
    subscribe — pass-through к внутреннему EventBus.

    Удовлетворяет ``event_module.EventBusProtocol`` (структурно).

    Pre:
      parent: опциональный QObject-родитель (стандартная семантика Qt ownership).

    Post:
      subscribe(event_type, handler) -> Subscription (не None).
      publish(event): если main thread — синхронный вызов handler'ов.
                      если worker thread — delivery через QueuedConnection
                      (async, на main thread, до следующей итерации event-loop'а).

    Invariants:
      Внутренний EventBus не имеет Qt-зависимостей (event_module чистый).
      Все ошибки subscriber'ов логируются через logging, не поглощаются.
      Мост generic по типу события (object) — не завязан на прототип-события.
    """

    # Внутренний сигнал для маршалинга с worker thread на main thread.
    # Signal(object) в PySide6 поддерживает любые Python-объекты.
    # При emit() из другого thread'а — Qt автоматически выбирает QueuedConnection.
    _worker_event = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Инициализируем внутренний bus с кастомным error_handler для логирования
        self._bus = EventBus(error_handler=self._on_error)
        # QueuedConnection форсирует доставку через event loop main thread'а,
        # даже если emit() произошёл с main thread (но в этом случае мы идём
        # синхронным путём в publish() и emit() не вызываем).
        self._worker_event.connect(
            self._dispatch_on_main,
            Qt.ConnectionType.QueuedConnection,
        )

    # ------------------------------------------------------------------
    # Публичный API (EventBusProtocol)
    # ------------------------------------------------------------------

    def publish(self, event: object) -> None:
        """Опубликовать событие (любого типа — мост непрозрачен к типу).

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

        Pass-through к внутреннему EventBus.subscribe().
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
        self._bus.publish(event)

    # ------------------------------------------------------------------
    # Error handler для внутреннего EventBus
    # ------------------------------------------------------------------

    def _on_error(self, exc: Exception, event: object) -> None:
        """Логировать ошибку subscriber'а через стандартный logging.

        Не поглощает исключение молча — соответствует правилу 5 CLAUDE.md.
        """
        _logger.exception(
            "QtEventBus: subscriber raised for event %r: %s",
            event,
            exc,
        )


__all__ = ["QtEventBus"]
