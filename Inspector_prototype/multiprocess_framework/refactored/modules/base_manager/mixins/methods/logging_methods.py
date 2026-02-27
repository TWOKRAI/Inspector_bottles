"""
Методы логирования для ObservableMixin.
"""

from typing import Dict, Any, Callable
import types


class LoggingMethods:
    """
    Методы логирования.
    
    Внутренний компонент ObservableMixin, предоставляющий приватные методы логирования.
    """
    
    @staticmethod
    def create_logging_methods(instance: Any, call_manager_func: Callable):
        """
        Создать методы логирования на экземпляре.
        
        Использует types.MethodType для создания pickle-совместимых методов.
        
        Args:
            instance: Экземпляр для создания методов
            call_manager_func: Функция для вызова менеджера
        """
        # Сохраняем call_manager_func как атрибут для pickle-совместимости
        instance._call_manager_func = call_manager_func
        
        # Создаем методы как bound methods класса для pickle-совместимости
        # ВАЖНО: _log_method должна быть определена как метод, который можно вызывать из других методов
        def _log_method(self, level: str, message: str, **kwargs):
            """Логирование через logger_manager."""
            if hasattr(self, '_call_manager_func'):
                self._call_manager_func('logger', level, message, **kwargs)
        
        # Сохраняем _log_method как атрибут экземпляра для доступа из других методов
        instance._log_method_internal = types.MethodType(_log_method, instance)
        
        def _log_debug_method(self, msg, **kw):
            """Логирование уровня debug."""
            if hasattr(self, '_log_method_internal'):
                self._log_method_internal("debug", msg, **kw)
        
        def _log_info_method(self, msg, **kw):
            """Логирование уровня info."""
            if hasattr(self, '_log_method_internal'):
                self._log_method_internal("info", msg, **kw)
        
        def _log_warning_method(self, msg, **kw):
            """Логирование уровня warning."""
            if hasattr(self, '_log_method_internal'):
                self._log_method_internal("warning", msg, **kw)
        
        def _log_error_method(self, msg, **kw):
            """Логирование уровня error."""
            if hasattr(self, '_log_method_internal'):
                self._log_method_internal("error", msg, **kw)
        
        def _log_critical_method(self, msg, **kw):
            """Логирование уровня critical."""
            if hasattr(self, '_log_method_internal'):
                self._log_method_internal("critical", msg, **kw)
        
        # Привязываем методы к экземпляру
        instance._log = types.MethodType(_log_method, instance)
        instance._log_debug = types.MethodType(_log_debug_method, instance)
        instance._log_info = types.MethodType(_log_info_method, instance)
        instance._log_warning = types.MethodType(_log_warning_method, instance)
        instance._log_error = types.MethodType(_log_error_method, instance)
        instance._log_critical = types.MethodType(_log_critical_method, instance)





