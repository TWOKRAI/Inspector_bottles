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

#: Маркер записи-АГРЕГАТА в stats-слоте (задача 2.1). Ставится тем, кто кладёт
#: готовый снапшот окна (:meth:`ObservabilityHub.emit_stats_record`), и читается
#: ТРЕМЯ потребителями сразу:
#:
#:   1. :func:`..observability.record_display.hub_record_to_display` — ветка
#:      нормализатора: у агрегата нет ни ``metric``, ни ``value``, и правило
#:      «четыре ключа» превратило бы его в пустую строку БД;
#:   2. :meth:`..observability.drain_adapter.ObservabilityDrainAdapter.apply_stat`
#:      — предохранитель от петли: агрегат НЕ возвращается в ``StatsManager``,
#:      иначе весь агрегат свернулся бы там в одну безымянную метрику и
#:      отравлял бы каждое следующее окно (форма вреда замерена — ADR-CRM-015);
#:   3. тесты — поимённая проверка класса записей.
#:
#: **Признак ровно один на все три места.** Второй независимый признак того же
#: класса (скажем, «нет ключа metric» у нормализатора против маркера у адаптера)
#: разошёлся бы с первым молча: запись, для одного агрегат, а для другого сырая
#: метрика, прошла бы петлёй мимо предохранителя (M2 ревью №3 спеки).
STATS_AGGREGATE_KEY = "aggregate"


def _serialize_exception(error: BaseException) -> Dict[str, Any]:
    """Привести исключение к pickle-safe dict (Dict at Boundary).

    Сам объект Exception через границу процесса не гоняем — только тип, текст и
    (если есть) отформатированный traceback.
    """
    if isinstance(error, BaseException):
        tb = getattr(error, "__traceback__", None)
        tb_str = "".join(_tb.format_exception(type(error), error, tb)) if tb is not None else None
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

    def _envelope(self, kind: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """Проставить общий конверт (kind/module/ts) — без записи в канал."""
        record["kind"] = kind
        record["module"] = self._module
        record["ts"] = self._clock()
        return record

    def _emit(self, kind: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """Конверт + запись в канал kind. Возвращает ЗАПИСЬ (контракт error-пути:
        ``track_error``/``record_error`` обязаны вернуть non-None, иначе
        ``ObservableMixin._track_error`` сделает fallback и запишет ошибку дважды)."""
        record = self._envelope(kind, record)
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

    def _emit_stat(self, metric_name: str, value: Any, metric_type: str, tags: Optional[Dict[str, str]]) -> None:
        self._emit(
            KIND_STATS,
            {
                "metric": metric_name,
                "value": value,
                "metric_type": metric_type,
                "tags": dict(tags or {}),
            },
        )

    def record_metric(self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None) -> None:
        """Прибавить ПРИРОСТ к счётчику (counter) — эмитит METRIC_COUNTER, не уровень.

        Задача S-4: до этой правки метод эмитил METRIC_GAUGE и дублировал
        :meth:`gauge` — одно значение под двумя именами. Хуже того, имя
        совпадало с :meth:`StatsManager.record_metric
        <...statistics_module.core.stats_manager.StatsManager.record_metric>`,
        а тот метод ВСЕГДА означает counter. Оба объекта — hub и реальный
        ``StatsManager`` — духк-тайпово садятся в один слот ``"stats"``
        :class:`~...base_manager.mixins.observable_mixin.ObservableMixin`
        (см. шапку модуля), и вызывающий, который зовёт
        ``self._record_metric(...)``, не может по месту вызова узнать, кто
        сейчас за слотом. Свип S-4 (перепроверен) не нашёл ни одного боевого
        вызывающего на момент правки — но слот духк-тайпован, и первый же
        ``self._record_metric(...)`` внутри ``worker_manager`` получил бы
        молчаливую перезапись там, где ждал сумму за окно.

        Совпадение имени со ``StatsManager.record_metric`` — НЕ случайность,
        а обязательный инвариант: одно имя обязано значить одну и ту же вещь
        под обоими менеджерами. Нужен снимок текущего значения (перезапись,
        а не сумма) — зови :meth:`gauge`; не «чини» этот метод обратно на
        GAUGE, если понадобится точечное значение.
        """
        self._emit_stat(metric_name, value, METRIC_COUNTER, tags)

    def increment(self, metric_name: str, value: Any = 1, tags: Optional[Dict[str, str]] = None) -> None:
        self._emit_stat(metric_name, value, METRIC_COUNTER, tags)

    def record_timing(self, metric_name: str, duration: float, tags: Optional[Dict[str, str]] = None) -> None:
        self._emit_stat(metric_name, duration, METRIC_TIMING, tags)

    def gauge(self, metric_name: str, value: Any, tags: Optional[Dict[str, str]] = None) -> None:
        self._emit_stat(metric_name, value, METRIC_GAUGE, tags)

    def emit_stats_record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Положить в stats-слот ГОТОВУЮ запись — не одну метрику (задача 2.1).

        До этой правки у hub'а был ровно один писатель stats-слота
        (:meth:`_emit_stat`), и он навязывал форму «одна запись на метрику»:
        ``{metric, value, metric_type, tags}``. Снапшот окна агрегации в эту
        форму не ложится — он про НАБОР метрик за окно, а разложить его на
        записи-по-метрике значило бы 8 процессов × 20 метрик × 360 окон/ч =
        57 600 строк/ч в стор (в 11 раз больше всего сегодняшнего темпа).
        Поэтому метод принимает готовый payload и только проставляет общий
        конверт — ``kind``/``module``/``ts``, как всем остальным записям.

        **Форма payload'а hub не проверяет и не знает** — он примитив уровня 0:
        его дело положить pickle-safe dict в bounded-канал под правильным
        ``kind``. Смысл содержимого — договор писателя (``HubStatsChannel``) и
        читателей (нормализатор, drain-адаптер), и держится он на маркере
        :data:`STATS_AGGREGATE_KEY`, который писатель обязан поставить сам:
        поставь его здесь — и «положить готовую запись» стало бы синонимом
        «положить агрегат», а метод общий.

        Копия входного dict'а, а не он сам: снапшот принадлежит вызывающему,
        и конверт hub'а не должен появляться в чужом объекте задним числом.

        **Возвращается РЕЗУЛЬТАТ ЗАПИСИ, а не сама запись.** Прежняя редакция
        отдавала запись с конвертом, и писатель не мог отличить «легло» от
        «вытеснило старейшую»: канал bounded (ёмкость 1024), при заторе дренажа
        он вытесняет молча и растит свой счётчик. Замер ревью 2.1 — 1100 окон без
        дренажа: `hub.dropped['stats'] = 76`, а канал рапортовал `success` 1100
        раз. Счётчик потерь виден снаружи (`introspect.observability`), но
        арифметика «эмитировано = доставлено + подавлено» считалась по книгам
        писателя и сходилась даже при вытеснении.

        Args:
            payload: содержимое записи (без конверта).

        Returns:
            То, что вернул bounded-канал: ``{"status": "success"|"dropped",
            "channel": …, "dropped": <накопленный счётчик>}``. Сам конверт
            писателю возвращать незачем — ``ts`` он всё равно не выбирает.
        """
        return self._channels[KIND_STATS].write(self._envelope(KIND_STATS, dict(payload)))

    # ------------------------------------------------------------------
    # ErrorLike
    # ------------------------------------------------------------------

    def _emit_error(self, error: BaseException, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
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
    def track_error(self, error: BaseException, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._emit_error(error, context)

    def record_error(self, error: BaseException, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
