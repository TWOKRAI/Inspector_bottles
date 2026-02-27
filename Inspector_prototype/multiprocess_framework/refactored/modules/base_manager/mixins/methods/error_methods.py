"""
Методы отслеживания ошибок для ObservableMixin.
"""

from typing import Dict, Any, Callable
import types


class ErrorMethods:
    """
    Методы отслеживания ошибок.
    
    Внутренний компонент ObservableMixin, предоставляющий приватные методы отслеживания ошибок.
    """
    
    @staticmethod
    def create_error_methods(instance: Any, call_manager_func: Callable):
        """
        Создать методы отслеживания ошибок на экземпляре.
        
        Использует types.MethodType для создания pickle-совместимых методов.
        
        Args:
            instance: Экземпляр для создания методов
            call_manager_func: Функция для вызова менеджера
        """
        # Сохраняем call_manager_func как атрибут для pickle-совместимости
        instance._call_manager_func = call_manager_func
        
        # Создаем методы как bound methods класса для pickle-совместимости
        def _track_error_method(self, error: Exception, context: Dict[str, Any] = None):
            """Отслеживание ошибки через error_manager."""
            if hasattr(self, '_call_manager_func'):
                # Пробуем track_error через error_manager
                result = self._call_manager_func('error', 'track_error', error, context or {})
                if result is not None:
                    return result
                # Fallback на errors_manager
                result = self._call_manager_func('errors', 'track_error', error, context or {})
                if result is not None:
                    return result
                # Последний fallback на record_error только если ни один track_error не сработал
                # Проверяем что менеджер существует перед вызовом
                return self._call_manager_func('error', 'record_error', error, context or {})
        
        # Привязываем метод к экземпляру
        instance._track_error = types.MethodType(_track_error_method, instance)





