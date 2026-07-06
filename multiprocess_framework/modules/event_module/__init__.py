# -*- coding: utf-8 -*-
"""
event_module — generic typed in-proc pub/sub (события-факты).

EventBus -- pure Python synchronous typed pub/sub (диспетчеризация по type(event)).
ErrorHandler -- тип callback'а обработки ошибок subscriber'а.
EventBusProtocol / Subscription -- контракты для DI и Qt-обёрток.

Generic: тип события не ограничен — переиспользуется любым приложением.
Qt-thread-safety — отдельная обёртка на стороне приложения (не в этом модуле).
"""

from .event_bus import ErrorHandler, EventBus
from .interfaces import EventBusProtocol, Subscription

__all__ = [
    "EventBus",
    "ErrorHandler",
    "EventBusProtocol",
    "Subscription",
]
