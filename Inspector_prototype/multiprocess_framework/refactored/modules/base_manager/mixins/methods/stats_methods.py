"""
Методы статистики для ObservableMixin.
"""

from typing import Dict, Any, Callable
import types


class StatsMethods:
    """
    Методы статистики.
    
    Внутренний компонент ObservableMixin, предоставляющий приватные методы статистики.
    """
    
    @staticmethod
    def create_stats_methods(instance: Any, call_manager_func: Callable):
        """
        Создать методы статистики на экземпляре.
        
        Использует types.MethodType для создания pickle-совместимых методов.
        
        Args:
            instance: Экземпляр для создания методов
            call_manager_func: Функция для вызова менеджера
        """
        # Сохраняем call_manager_func как атрибут для pickle-совместимости
        instance._call_manager_func = call_manager_func
        
        # Создаем методы как bound methods класса для pickle-совместимости
        def _record_metric_method(self, metric_name: str, value: Any = 1, tags: Dict[str, str] = None):
            """Запись метрики через statistics_manager."""
            if hasattr(self, '_call_manager_func'):
                if not self._call_manager_func('statistics', 'record_metric', metric_name, value, tags or {}):
                    # Fallback на stats или increment
                    if not self._call_manager_func('stats', 'record_metric', metric_name, value, tags or {}):
                        self._call_manager_func('statistics', 'increment', metric_name, tags or {})
        
        def _record_timing_method(self, metric_name: str, duration: float, tags: Dict[str, str] = None):
            """Запись времени выполнения через statistics_manager."""
            if hasattr(self, '_call_manager_func'):
                if not self._call_manager_func('statistics', 'record_timing', metric_name, duration, tags or {}):
                    # Fallback на stats или timing
                    if not self._call_manager_func('stats', 'record_timing', metric_name, duration, tags or {}):
                        self._call_manager_func('statistics', 'timing', metric_name, duration, tags or {})
        
        # Привязываем методы к экземпляру
        instance._record_metric = types.MethodType(_record_metric_method, instance)
        instance._record_timing = types.MethodType(_record_timing_method, instance)





