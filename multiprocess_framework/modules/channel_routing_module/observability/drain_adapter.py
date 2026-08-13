# -*- coding: utf-8 -*-
"""
ObservabilityDrainAdapter — переводчик dict-записей hub'а в вызовы sink-менеджеров.

Задача Ф5.16 (a): `ObservabilityHub` кладёт в свои каналы pickle-safe dict-записи
(см. observability_hub.py: log/error/stats-формы). Владелец процесса дренирует их
по heartbeat и должен слить в РЕАЛЬНЫЕ менеджеры-sink'и — но у sink'ов НЕТ методов
`dispatch/track/record` из docstring-примера hub'а. Реальные точки входа:

    - Logger:  LoggerCore.debug/info/warning/error/critical(message, module, **extra)
    - Error:   ErrorManager — тот же severity-именованный набор (наследник LoggerCore),
               его log()-override делает level-routing по severity
    - Stats:   StatsManager.record_metric / record_timing / gauge(name, value, tags)

Адаптер — чистый переводчик: **duck-typed**, НЕ импортирует классы менеджеров
(иначе core-слой channel_routing получил бы обратную связь на logger/error/stats).
Sink'и передаются в конструктор, вызовы идут по имени метода.

Паритет-по-построению: адаптер бьёт в те же severity-именованные методы, что
дёргал прямой путь ObservableMixin (`_call_manager("logger", severity, msg, **kw)`),
поэтому «запись напрямую в менеджер» и «эмиссия→hub→drain→adapter→менеджер» дают
идентичный вызов sink'а (ts — из записи hub'а, детерминируется `clock=`).

Контракт (Design-by-Contract):

    apply_log(record)
        Pre:  record — dict log-записи hub'а: {'severity','message','context',...}.
        Post: вызван getattr(logger, severity)(message, module, **context), если
              logger-sink задан; вернул True при доставке, False если sink=None.
        Inv:  неизвестный severity → уровень 'info' (лог не теряется).

    apply_error(record)
        Pre:  record — dict error-записи hub'а:
              {'error_type','message','traceback','context','severity',...}.
        Post: severity-роутинг ErrorManager воспроизведён — вызван
              getattr(error, severity)(full_message, module), где full_message
              собран из error_type/message/traceback; True/False по наличию sink.
        Inv:  неизвестный/пустой severity → 'error'.

    apply_stat(record)
        Pre:  record — dict stats-записи hub'а:
              {'metric','value','metric_type','tags',...}.
        Post: по metric_type вызван record_metric(counter)/record_timing(timing)/
              gauge(gauge) на stats-sink'е; True/False по наличию sink.
        Inv:  неизвестный metric_type → record_metric (значение не теряется).
        Inv:  запись с маркером STATS_AGGREGATE_KEY в sink НЕ идёт (2.1: это
              снапшот, который построил сам sink — петля) и считается в
              ``skipped_aggregates``.

    apply_drained(drained)
        Pre:  drained — выход hub.drain_all(): {'log':[...],'error':[...],'stats':[...]}.
        Post: каждая запись слита соответствующим apply_*; порядок сохранён.
"""

from typing import Any, Dict, List, Optional

from ..levels import LEVEL_ORDER
from .observability_hub import (
    KIND_ERROR,
    KIND_LOG,
    KIND_STATS,
    METRIC_COUNTER,
    METRIC_GAUGE,
    METRIC_TIMING,
    STATS_AGGREGATE_KEY,
)

# Разрешённые severity-имена методов на Logger/Error sink'ах — ВЫВЕДЕНЫ из
# общего порядка уровней, а не своей копией списка (Ф3.1). Копия здесь уже
# была: новый уровень требовал правки в двух местах, и расхождение
# проявилось бы тем, что запись законного уровня молча переписывается в
# 'info' ниже по коду. Имена методов на sink'ах строчные (PEP8) — это
# написание вызова, а не второй словарь уровней.
_LOG_SEVERITIES = frozenset(name.lower() for name in LEVEL_ORDER)


class ObservabilityDrainAdapter:
    """Переводит дренированные dict-записи hub'а в вызовы sink-менеджеров.

    Duck-typed: sink'и — любые объекты с нужными методами (LoggerManager /
    ErrorManager / StatsManager или их моки в тестах). Любой sink может быть
    None — тогда соответствующий kind тихо пропускается (apply_* вернёт False).
    """

    def __init__(
        self,
        logger: Optional[Any] = None,
        stats: Optional[Any] = None,
        error: Optional[Any] = None,
    ) -> None:
        self._logger = logger
        self._stats = stats
        self._error = error
        # Задача 2.1: сколько записей-агрегатов предохранитель НЕ отдал в
        # StatsManager. ``apply_stat`` возвращает False и на «нет стока», и на
        # «это агрегат» — одно и то же число снаружи означало бы две разные
        # вещи. Намеренная не-доставка обязана считаться отдельно от отсутствия
        # получателя (тот же счёт, что у ``empty_suppressed`` окна агрегации).
        self._skipped_aggregates = 0

    # ------------------------------------------------------------------
    # Одиночные записи
    # ------------------------------------------------------------------

    def apply_log(self, record: Dict[str, Any]) -> bool:
        if self._logger is None:
            return False
        severity = record.get("severity", "info")
        if severity not in _LOG_SEVERITIES:
            severity = "info"
        context = dict(record.get("context") or {})
        # Тот же вызов, что делал прямой путь ObservableMixin:
        # _call_manager("logger", severity, msg, **kw) → паритет по построению.
        getattr(self._logger, severity)(record.get("message", ""), **context)
        return True

    def apply_error(self, record: Dict[str, Any]) -> bool:
        if self._error is None:
            return False
        severity = record.get("severity") or "error"
        if severity not in _LOG_SEVERITIES:
            severity = "error"
        # Объект исключения через границу hub'а не пережил — восстанавливаем
        # человекочитаемое сообщение из сериализованных полей.
        error_type = record.get("error_type")
        message = record.get("message", "")
        full = f"{error_type}: {message}" if error_type else message
        traceback = record.get("traceback")
        if traceback:
            full = f"{full}\n{traceback}"
        module = record.get("context", {}).get("module") or record.get("module") or "unknown"
        getattr(self._error, severity)(full, module=module)
        return True

    def apply_stat(self, record: Dict[str, Any]) -> bool:
        """Сырую метрику — в ``StatsManager``; АГРЕГАТ — мимо него (задача 2.1).

        Работа адаптера — доносить до менеджера сырые числа ЧУЖИХ владельцев
        (``WorkerManager`` эмитит в hub, менеджер агрегирует). Снапшот окна
        приходит с противоположной стороны: его ``StatsManager`` сам и построил.

        **Что происходит без предохранителя — замерено, а не предположено**
        (прогон со снятой проверкой, 5 окон): у агрегата нет ни ``metric``, ни
        ``value``, ни ``metric_type``, поэтому инвариант «неизвестный тип не
        теряем» ниже сворачивает ВЕСЬ снапшот в одну безымянную метрику —
        ``record_metric("", 1)``. Начиная со второго окна каждый снапшот несёт
        фантомную серию ``('', 1.0)``, и «сколько метрик было в окне» врёт на
        каждом процессе до конца смены.

        **Число СТРОК при этом остаётся линейным** (одно окно — один снапшот),
        поэтому тест, считающий строки, петлю НЕ ловит; красным её делает счёт
        СЕРИЙ внутри записи. Прежняя редакция этого докстринга обещала «рост
        каждое окно, пока не упрётся в потолок канала» — правдоподобно и неверно.

        Стор и форвардеры берут пачку целиком: у них агрегат — законная запись,
        а петли нет, они не эмитенты.

        Различитель — :data:`STATS_AGGREGATE_KEY`, тот же самый, по которому
        ветвится нормализатор display-вида. Второго признака у этого класса
        записей нет намеренно (см. докстринг константы).
        """
        if record.get(STATS_AGGREGATE_KEY):
            self._skipped_aggregates += 1
            return False
        if self._stats is None:
            return False
        name = record.get("metric", "")
        value = record.get("value", 1)
        tags = dict(record.get("tags") or {})
        metric_type = record.get("metric_type")
        if metric_type == METRIC_COUNTER:
            self._stats.record_metric(name, value, tags)
        elif metric_type == METRIC_TIMING:
            self._stats.record_timing(name, value, tags)
        elif metric_type == METRIC_GAUGE:
            self._stats.gauge(name, value, tags)
        else:
            # Инвариант: неизвестный тип не теряем — пишем как метрику.
            self._stats.record_metric(name, value, tags)
        return True

    # ------------------------------------------------------------------
    # Пакетный дренаж
    # ------------------------------------------------------------------

    @property
    def skipped_aggregates(self) -> int:
        """Сколько записей-агрегатов не поехало обратно в ``StatsManager`` (2.1)."""
        return self._skipped_aggregates

    def apply_drained(self, drained: Dict[str, List[Dict[str, Any]]]) -> None:
        for rec in drained.get(KIND_LOG, ()):  # порядок каналов сохранён
            self.apply_log(rec)
        for rec in drained.get(KIND_ERROR, ()):
            self.apply_error(rec)
        for rec in drained.get(KIND_STATS, ()):
            self.apply_stat(rec)
