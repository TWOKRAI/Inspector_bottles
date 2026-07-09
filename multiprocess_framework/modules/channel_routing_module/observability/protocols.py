# -*- coding: utf-8 -*-
"""
Duck-type протоколы наблюдаемости — контракт слотов ObservableMixin.

ObservableMixin доставляет наблюдаемость через слоты `{'logger','stats','error'}`,
вызывая на них методы по имени (утиная типизация, без импорта менеджеров).
Эти Protocol'ы фиксируют, ЧТО именно вызывается на каждом слоте — и ObservabilityHub
реализует все три сразу, оставаясь drop-in заменой любого из менеджеров.

Контракты nam-в-нам совпадают с вызовами ObservableMixin:
    logger : _call_manager('logger', <level>, message, **kwargs)  → debug…critical
    stats  : _call_manager('stats', 'record_metric'|'record_timing', name, value, tags)
    error  : _call_manager('error', 'track_error'|'record_error', error, context)
"""

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class LoggerLike(Protocol):
    """Слот 'logger': уровни логирования, которые дергает ObservableMixin._log_*."""

    def debug(self, message: str, **kwargs: Any) -> None: ...
    def info(self, message: str, **kwargs: Any) -> None: ...
    def warning(self, message: str, **kwargs: Any) -> None: ...
    def error(self, message: str, **kwargs: Any) -> None: ...
    def critical(self, message: str, **kwargs: Any) -> None: ...


@runtime_checkable
class StatsLike(Protocol):
    """Слот 'stats': метрики, счётчики, тайминги, gauge."""

    def record_metric(
        self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None
    ) -> None: ...
    def increment(
        self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None
    ) -> None: ...
    def record_timing(
        self, metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None
    ) -> None: ...
    def gauge(
        self, metric_name: str, value: Any, tags: Optional[Dict[str, str]] = None
    ) -> None: ...


@runtime_checkable
class ErrorLike(Protocol):
    """Слот 'error': трекинг ошибок с контекстом.

    Возврат — Any: ObservableMixin._track_error трактует non-None как «обработано»
    и НЕ делает fallback track_error → record_error (иначе на слоте с обоими
    методами ошибка записалась бы дважды).
    """

    def track_error(
        self, error: BaseException, context: Optional[Dict[str, Any]] = None
    ) -> Any: ...
    def record_error(
        self, error: BaseException, context: Optional[Dict[str, Any]] = None
    ) -> Any: ...
