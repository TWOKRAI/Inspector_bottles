"""
Встроенные плагины для ObservableMixin.

Примеры плагинов для стандартных менеджеров.
"""

from typing import Dict, Any, Callable
from .plugin_base import ObservablePlugin


class LoggerPlugin(ObservablePlugin):
    """
    Плагин для стандартного логгера.
    
    Пример использования:
        plugin = LoggerPlugin()
        ObservableMixin.__init__(..., plugins=[plugin])
    """
    
    def get_manager_names(self) -> list[str]:
        return ['logger']
    
    def create_proxy_methods(
        self,
        instance: Any,
        managers: Dict[str, Any],
        call_manager_func: Callable
    ) -> None:
        """
        Создать прокси-методы для логгера.
        
        ВАЖНО: Методы создаются всегда, даже если logger manager не зарегистрирован.
        Если logger не зарегистрирован, _call_manager вернет None, что безопасно.
        Логирование должно идти через logger manager, если он доступен.
        
        ИСПРАВЛЕНО: Используются обычные функции вместо лямбда для совместимости с pickle.
        """
        # Создаем методы всегда - они будут вызывать logger manager через _call_manager
        # Если logger manager не зарегистрирован, _call_manager вернет None (безопасно)
        # Логирование должно идти через logger manager, поэтому используем прямой вызов
        # ВАЖНО: Используем обычные функции вместо лямбда для совместимости с pickle (multiprocessing на Windows)
        
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
    Плагин для статистики.
    
    Поддерживает оба имени: 'stats' и 'statistics'.
    """
    
    def get_manager_names(self) -> list[str]:
        return ['stats', 'statistics']
    
    def create_proxy_methods(
        self,
        instance: Any,
        managers: Dict[str, Any],
        call_manager_func: Callable
    ) -> None:
        """
        Создать прокси-методы для статистики.
        
        ИСПРАВЛЕНО: Используются обычные функции вместо лямбда для совместимости с pickle.
        """
        stats_name = None
        if 'stats' in managers:
            stats_name = 'stats'
        elif 'statistics' in managers:
            stats_name = 'statistics'
        
        if stats_name:
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
    Плагин для отслеживания ошибок.
    
    Поддерживает оба имени: 'error' и 'errors'.
    """
    
    def get_manager_names(self) -> list[str]:
        return ['error', 'errors']
    
    def create_proxy_methods(
        self,
        instance: Any,
        managers: Dict[str, Any],
        call_manager_func: Callable
    ) -> None:
        """
        Создать прокси-методы для отслеживания ошибок.
        
        ИСПРАВЛЕНО: Используются обычные функции вместо лямбда для совместимости с pickle.
        """
        error_name = None
        if 'errors' in managers:
            error_name = 'errors'
        elif 'error' in managers:
            error_name = 'error'
        
        if error_name:
            def track_error(error, context=None):
                return call_manager_func(error_name, 'track_error', error, context or {})
            
            def record_error(error, context=None):
                return call_manager_func(error_name, 'record_error', error, context or {})
            
            instance.track_error = track_error
            instance.record_error = record_error





