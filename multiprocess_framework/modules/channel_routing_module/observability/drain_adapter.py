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

    apply_drained(drained)
        Pre:  drained — выход hub.drain_all(): {'log':[...],'error':[...],'stats':[...]}.
        Post: каждая запись слита соответствующим apply_*; порядок сохранён.
"""

from typing import Any, Dict, List, Optional


# Разрешённые severity-имена методов на Logger/Error sink'ах.
_LOG_SEVERITIES = frozenset({"debug", "info", "warning", "error", "critical"})


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

    # ------------------------------------------------------------------
    # Одиночные записи
    # ------------------------------------------------------------------

    def apply_log(self, record: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def apply_error(self, record: Dict[str, Any]) -> bool:
        raise NotImplementedError

    def apply_stat(self, record: Dict[str, Any]) -> bool:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Пакетный дренаж
    # ------------------------------------------------------------------

    def apply_drained(self, drained: Dict[str, List[Dict[str, Any]]]) -> None:
        raise NotImplementedError
