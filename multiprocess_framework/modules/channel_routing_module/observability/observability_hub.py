# -*- coding: utf-8 -*-
"""
ObservabilityHub — фасад наблюдаемости одного модуля (уровень 0).

Идея (observability-hub-idea.md, задача Ф5.15): модуль = «электронное
устройство» с тремя выходами-сигналами — log / error / stats. Все подмодули и
классы модуля эмитят через ObservableMixin в ЕДИНЫЙ hub, а hub вместо доставки
кладёт pickle-safe dict-записи в свои bounded-каналы с тегом модуля. Владелец
(composition root процесса) забирает записи по такту heartbeat через drain_*()
и сам решает, куда их слить (LoggerManager / ErrorManager / StatsManager,
локально или через RouterManager в оркестратор — уровень 1, задача Ф5.16).

Hub реализует duck-type протоколы LoggerLike / StatsLike / ErrorLike (см.
protocols.py), поэтому является drop-in заменой для слотов ObservableMixin
`{'logger','stats','error'}` без единой правки внутри модулей:

    hub = ObservabilityHub("worker_module", capacity=1024)
    manager = WorkerManager(..., logger=hub, stats=hub, error=hub)   # duck-type
    # владелец процесса, по heartbeat:
    for rec in hub.drain_logs():   logger_manager.dispatch(rec)
    for rec in hub.drain_errors(): error_manager.track(rec)
    for rec in hub.drain_stats():  stats_manager.record(rec)

Дизайн (см. DECISIONS.md, ADR ObservabilityHub):
    - kind-роутинг записи в нужный канал — in-process аналог route(key_field="kind");
    - записи — pickle-safe dict (Dict at Boundary): исключение сериализуется,
      severity/context сохраняются для severity-роутинга ErrorManager;
    - overflow — drop_oldest + счётчик потерь на каждый канал (не молчим о потере);
    - hub НЕ обязан быть pickle-safe: слоты переинъектит владелец после unpickle.
"""

import time
import traceback as _tb
from typing import Any, Callable, Dict, List, Optional

from .bounded_channel import DROP_OLDEST, BoundedChannel

KIND_LOG = "log"
KIND_ERROR = "error"
KIND_STATS = "stats"

# Типы метрик — фиксируем в записи, чтобы StatsManager роутил без догадок.
METRIC_GAUGE = "gauge"
METRIC_COUNTER = "counter"
METRIC_TIMING = "timing"


def _serialize_exception(error: BaseException) -> Dict[str, Any]:
    """Привести исключение к pickle-safe dict (Dict at Boundary).

    Сам объект Exception через границу процесса не гоняем — только тип, текст и
    (если есть) отформатированный traceback.
    """
    if isinstance(error, BaseException):
        tb = getattr(error, "__traceback__", None)
        tb_str = (
            "".join(_tb.format_exception(type(error), error, tb)) if tb is not None else None
        )
        return {
            "error_type": type(error).__name__,
            "message": str(error),
            "traceback": tb_str,
        }
    # Защита от не-исключений (на случай, если прилетело что-то иное).
    return {"error_type": "NonException", "message": str(error), "traceback": None}


class ObservabilityHub:
    """Перехватчик наблюдаемости модуля: 3 bounded-канала + pull-дренаж."""

    def __init__(
        self,
        module_name: str,
        capacity: int = 1024,
        overflow: str = DROP_OLDEST,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """
        Args:
            module_name: Тег модуля, проставляется в каждую запись.
            capacity:    Ёмкость каждого из трёх каналов (log/error/stats).
            overflow:    Политика переполнения каналов ("drop_oldest"|"drop_newest").
            clock:       Источник времени (инъекция для детерминизма в тестах).
        """
        self._module = module_name
        self._clock = clock
        self._log_channel = BoundedChannel(f"{module_name}.{KIND_LOG}", capacity, overflow)
        self._error_channel = BoundedChannel(f"{module_name}.{KIND_ERROR}", capacity, overflow)
        self._stats_channel = BoundedChannel(f"{module_name}.{KIND_STATS}", capacity, overflow)
        self._channels: Dict[str, BoundedChannel] = {
            KIND_LOG: self._log_channel,
            KIND_ERROR: self._error_channel,
            KIND_STATS: self._stats_channel,
        }

    # ------------------------------------------------------------------
    # Внутренняя маршрутизация (in-process route по 'kind')
    # ------------------------------------------------------------------

    def _emit(self, kind: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """Проставить общий конверт (kind/module/ts), положить в канал kind, вернуть запись."""
        record["kind"] = kind
        record["module"] = self._module
        record["ts"] = self._clock()
        self._channels[kind].write(record)
        return record

    # ------------------------------------------------------------------
    # LoggerLike
    # ------------------------------------------------------------------

    def _emit_log(self, severity: str, message: str, **context: Any) -> None:
        self._emit(
            KIND_LOG,
            {"severity": severity, "message": message, "context": dict(context)},
        )

    def log(self, level: str, message: str, **kwargs: Any) -> None:
        """Обобщённый лог произвольного уровня (совместим с ObservableMixin._log)."""
        self._emit_log(level, message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._emit_log("debug", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._emit_log("info", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._emit_log("warning", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._emit_log("error", message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self._emit_log("critical", message, **kwargs)

    # ------------------------------------------------------------------
    # StatsLike
    # ------------------------------------------------------------------

    def _emit_stat(
        self, metric_name: str, value: Any, metric_type: str, tags: Optional[Dict[str, str]]
    ) -> None:
        self._emit(
            KIND_STATS,
            {
                "metric": metric_name,
                "value": value,
                "metric_type": metric_type,
                "tags": dict(tags or {}),
            },
        )

    def record_metric(
        self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        self._emit_stat(metric_name, value, METRIC_GAUGE, tags)

    def increment(
        self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None
    ) -> None:
        self._emit_stat(metric_name, value, METRIC_COUNTER, tags)

    def record_timing(
        self, metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None
    ) -> None:
        self._emit_stat(metric_name, duration, METRIC_TIMING, tags)

    def gauge(
        self, metric_name: str, value: Any, tags: Optional[Dict[str, str]] = None
    ) -> None:
        self._emit_stat(metric_name, value, METRIC_GAUGE, tags)

    # ------------------------------------------------------------------
    # ErrorLike
    # ------------------------------------------------------------------

    def _emit_error(
        self, error: BaseException, context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        ctx = dict(context or {})
        # severity-роутинг ErrorManager сохраняем: контекст может поднять уровень
        # (например critical), иначе — дефолт "error".
        severity = ctx.pop("severity", "error")
        record = _serialize_exception(error)
        record["context"] = ctx
        record["severity"] = severity
        return self._emit(KIND_ERROR, record)

    # ВАЖНО: track_error/record_error возвращают non-None (запись). ObservableMixin.
    # _track_error при None-возврате делает fallback track_error → record_error на
    # ТОМ ЖЕ слоте; так как hub реализует оба метода, None привёл бы к ДВОЙНОЙ
    # записи ошибки. Truthy-возврат гасит fallback → ровно одна запись.
    def track_error(
        self, error: BaseException, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return self._emit_error(error, context)

    def record_error(
        self, error: BaseException, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        return self._emit_error(error, context)

    # ------------------------------------------------------------------
    # Дренаж (pull-модель: забирает владелец)
    # ------------------------------------------------------------------

    def drain_logs(self) -> List[Dict[str, Any]]:
        return self._log_channel.drain()

    def drain_errors(self) -> List[Dict[str, Any]]:
        return self._error_channel.drain()

    def drain_stats(self) -> List[Dict[str, Any]]:
        return self._stats_channel.drain()

    def drain_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """Забрать всё разом: {'log': [...], 'error': [...], 'stats': [...]}."""
        return {
            KIND_LOG: self._log_channel.drain(),
            KIND_ERROR: self._error_channel.drain(),
            KIND_STATS: self._stats_channel.drain(),
        }

    # ------------------------------------------------------------------
    # Диагностика
    # ------------------------------------------------------------------

    @property
    def module_name(self) -> str:
        return self._module

    @property
    def dropped(self) -> Dict[str, int]:
        """Счётчики потерь по каналам: {'log': N, 'error': N, 'stats': N}."""
        return {kind: ch.dropped for kind, ch in self._channels.items()}

    def get_channel(self, kind: str) -> BoundedChannel:
        """Прямой доступ к каналу по kind (для диагностики/тестов)."""
        return self._channels[kind]

    def get_info(self) -> Dict[str, Any]:
        return {
            "module": self._module,
            "channels": {kind: ch.get_info() for kind, ch in self._channels.items()},
        }
