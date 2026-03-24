"""
Встроенные плагины ObservableMixin.

Каждый плагин добавляет публичные прокси-методы для стандартного менеджера.
Все функции — модульного уровня (не лямбда), pickle-совместимы на Windows (spawn).

Встроенные плагины:
    LoggerPlugin   → log_debug/info/warning/error/critical
    StatsPlugin    → record_metric, increment, record_timing, gauge
    ErrorPlugin    → track_error, record_error
"""

from typing import Dict, Any, Callable
from .plugin_base import ObservablePlugin


class LoggerPlugin(ObservablePlugin):
    """
    Плагин для стандартного логгера.

    Создаёт публичные прокси-методы только если менеджер 'logger' зарегистрирован.
    Поддерживает имена: 'logger'.

    Пример:
        ObservableMixin.__init__(
            self,
            managers={'logger': my_logger},
            plugins=[LoggerPlugin()],
            auto_proxy=True,
        )
        # Доступно: self.log_info("сообщение")
    """

    def get_manager_names(self) -> list:
        return ['logger']

    def create_proxy_methods(
        self,
        instance: Any,
        managers: Dict[str, Any],
        call_manager_func: Callable
    ) -> None:
        """
        Создать публичные методы логирования.

        Методы создаются только если 'logger' зарегистрирован.
        Это обеспечивает согласованность с StatsPlugin и ErrorPlugin:
        публичный метод появляется лишь при наличии соответствующего менеджера.
        """
        if 'logger' not in managers:
            return

        def log_debug(msg, **kw):
            return call_manager_func('logger', 'debug', msg, **kw)

        def log_info(msg, **kw):
            return call_manager_func('logger', 'info', msg, **kw)

        def log_warning(msg, **kw):
            return call_manager_func('logger', 'warning', msg, **kw)

        def log_error(msg, **kw):
            return call_manager_func('logger', 'error', msg, **kw)

        def log_critical(msg, **kw):
            return call_manager_func('logger', 'critical', msg, **kw)

        instance.log_debug = log_debug
        instance.log_info = log_info
        instance.log_warning = log_warning
        instance.log_error = log_error
        instance.log_critical = log_critical


class StatsPlugin(ObservablePlugin):
    """
    Плагин для менеджера статистики.

    Поддерживает имена: 'stats' (приоритет), 'statistics'.
    Создаёт методы только если хотя бы один из них зарегистрирован.

    Создаваемые методы: record_metric, increment, record_timing, gauge.
    """

    def get_manager_names(self) -> list:
        return ['stats', 'statistics']

    def create_proxy_methods(
        self,
        instance: Any,
        managers: Dict[str, Any],
        call_manager_func: Callable
    ) -> None:
        stats_name = None
        if 'stats' in managers:
            stats_name = 'stats'
        elif 'statistics' in managers:
            stats_name = 'statistics'

        if stats_name is None:
            return

        def record_metric(name, value=1, tags=None):
            return call_manager_func(stats_name, 'record_metric', name, value, tags or {})

        def increment(name, tags=None):
            return call_manager_func(stats_name, 'increment', name, tags or {})

        def record_timing(name, duration, tags=None):
            return call_manager_func(stats_name, 'record_timing', name, duration, tags or {})

        def gauge(name, value, tags=None):
            return call_manager_func(stats_name, 'gauge', name, value, tags or {})

        instance.record_metric = record_metric
        instance.increment = increment
        instance.record_timing = record_timing
        instance.gauge = gauge


class ErrorPlugin(ObservablePlugin):
    """
    Плагин для менеджера ошибок.

    Поддерживает имена: 'errors' (приоритет), 'error'.
    Создаёт методы только если хотя бы один из них зарегистрирован.

    Создаваемые методы: track_error, record_error.
    """

    def get_manager_names(self) -> list:
        return ['errors', 'error']

    def create_proxy_methods(
        self,
        instance: Any,
        managers: Dict[str, Any],
        call_manager_func: Callable
    ) -> None:
        error_name = None
        if 'errors' in managers:
            error_name = 'errors'
        elif 'error' in managers:
            error_name = 'error'

        if error_name is None:
            return

        def track_error(error, context=None):
            return call_manager_func(error_name, 'track_error', error, context or {})

        def record_error(error, context=None):
            return call_manager_func(error_name, 'record_error', error, context or {})

        instance.track_error = track_error
        instance.record_error = record_error
