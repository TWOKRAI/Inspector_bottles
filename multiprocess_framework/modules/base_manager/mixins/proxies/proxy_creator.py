"""
Создатель прокси-методов для ObservableMixin.

Автоматически создает публичные методы-прокси для стандартных менеджеров
(logger, stats/statistics, error).
"""

from typing import Callable, Any


class ProxyCreator:
    """
    Создатель прокси-методов.

    Внутренний компонент ObservableMixin, отвечающий за автоматическое
    создание публичных методов-прокси для стандартных менеджеров.
    """

    @staticmethod
    def create_proxy_methods(
        instance: Any,
        managers: dict,
        call_manager_func: Callable,
    ):
        """
        Создать прокси-методы на экземпляре.

        Args:
            instance:          Экземпляр для создания методов
            managers:          Словарь менеджеров
            call_manager_func: Функция для вызова менеджера
        """
        instance._proxy_created = True
        ProxyCreator._create_standard_proxies(instance, managers, call_manager_func)

    @staticmethod
    def _create_standard_proxies(instance: Any, managers: dict, call_manager_func: Callable):
        """Создать стандартные прокси-методы для logger, stats и error."""
        # --- Logger ---
        if "logger" in managers:

            def log_debug(msg, **kw):
                return call_manager_func("logger", "debug", msg, **kw)

            def log_info(msg, **kw):
                return call_manager_func("logger", "info", msg, **kw)

            def log_warning(msg, **kw):
                return call_manager_func("logger", "warning", msg, **kw)

            def log_error(msg, **kw):
                return call_manager_func("logger", "error", msg, **kw)

            def log_critical(msg, **kw):
                return call_manager_func("logger", "critical", msg, **kw)

            instance.log_debug = log_debug
            instance.log_info = log_info
            instance.log_warning = log_warning
            instance.log_error = log_error
            instance.log_critical = log_critical

        # --- Stats ---
        stats_name = None
        if "stats" in managers:
            stats_name = "stats"
        elif "statistics" in managers:
            stats_name = "statistics"

        if stats_name is not None:

            def record_metric(name, value=1, tags=None):
                return call_manager_func(stats_name, "record_metric", name, value, tags or {})

            def increment(name, tags=None):
                return call_manager_func(stats_name, "increment", name, tags or {})

            def record_timing(name, duration, tags=None):
                return call_manager_func(stats_name, "record_timing", name, duration, tags or {})

            def gauge(name, value, tags=None):
                return call_manager_func(stats_name, "gauge", name, value, tags or {})

            instance.record_metric = record_metric
            instance.increment = increment
            instance.record_timing = record_timing
            instance.gauge = gauge

        # --- Error ---
        # Task 5.16 (след 5.14): каноничный слот — 'error'. Legacy-alias 'errors'
        # убран — симметрия с ObservableMixin._track_error, который тоже пробует
        # только 'error'. Все точки регистрации переведены на 'error'.
        if "error" in managers:

            def track_error(error, context=None):
                return call_manager_func("error", "track_error", error, context or {})

            def record_error(error, context=None):
                return call_manager_func("error", "record_error", error, context or {})

            instance.track_error = track_error
            instance.record_error = record_error
