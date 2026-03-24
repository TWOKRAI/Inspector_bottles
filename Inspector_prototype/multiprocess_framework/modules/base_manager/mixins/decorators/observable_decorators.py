"""
Декораторы для ObservableMixin.
"""

from typing import Callable, Dict, Any
from functools import wraps
import time


class ObservableDecorators:
    """
    Декораторы для автоматического логирования и мониторинга.
    
    Внутренний компонент ObservableMixin, предоставляющий декораторы.
    """
    
    @staticmethod
    def create_decorators(instance: Any, call_manager_func: Callable, log_error_func: Callable, track_error_func: Callable, record_metric_func: Callable, record_timing_func: Callable):
        """
        Создать декораторы на экземпляре.
        
        Args:
            instance: Экземпляр для создания декораторов
            call_manager_func: Функция для вызова менеджера
            log_error_func: Функция логирования ошибок
            track_error_func: Функция отслеживания ошибок
            record_metric_func: Функция записи метрик
            record_timing_func: Функция записи времени выполнения
        """
        def logged(manager_name: str = 'logger', level: str = "info", log_args: bool = False, log_result: bool = False):
            """
            Декоратор для автоматического логирования вызовов методов.
            
            Args:
                manager_name: Имя менеджера для логирования (по умолчанию 'logger')
                level: Уровень логирования (debug, info, warning, error)
                log_args: Логировать аргументы метода
                log_result: Логировать результат выполнения
            """
            def decorator(func: Callable) -> Callable:
                @wraps(func)
                def wrapper(*args, **kwargs):
                    method_name = f"{func.__module__}.{func.__qualname__}"
                    
                    # Логирование начала выполнения
                    if log_args:
                        call_manager_func(manager_name, level, f"Calling {method_name}", args=args, kwargs=kwargs)
                    else:
                        call_manager_func(manager_name, level, f"Calling {method_name}")
                    
                    try:
                        result = func(*args, **kwargs)
                        
                        # Логирование результата
                        if log_result:
                            call_manager_func(manager_name, level, f"{method_name} completed", result=result)
                        
                        return result
                    except Exception as e:
                        log_error_func(f"{method_name} failed: {str(e)}")
                        track_error_func(e, {"method": method_name, "args": str(args), "kwargs": str(kwargs)})
                        raise
                
                return wrapper
            return decorator
        
        def timed(manager_name: str = 'statistics', metric_name: str = None, tags: Dict[str, str] = None):
            """
            Декоратор для автоматического измерения времени выполнения.
            
            Args:
                manager_name: Имя менеджера статистики (по умолчанию 'statistics')
                metric_name: Имя метрики (по умолчанию используется имя метода)
                tags: Теги для метрики
            """
            def decorator(func: Callable) -> Callable:
                @wraps(func)
                def wrapper(*args, **kwargs):
                    metric = metric_name or f"{func.__module__}.{func.__qualname__}"
                    start_time = time.time()
                    
                    try:
                        result = func(*args, **kwargs)
                        duration = time.time() - start_time
                        record_timing_func(metric, duration, tags)
                        return result
                    except Exception as e:
                        duration = time.time() - start_time
                        record_timing_func(f"{metric}.error", duration, tags)
                        raise
                
                return wrapper
            return decorator
        
        def monitored(manager_name: str = 'logger', level: str = "info", metric_name: str = None):
            """
            Комбинированный декоратор для логирования и статистики.
            
            Args:
                manager_name: Имя менеджера для логирования
                level: Уровень логирования
                metric_name: Имя метрики для статистики
            """
            def decorator(func: Callable) -> Callable:
                @wraps(func)
                def wrapper(*args, **kwargs):
                    method_name = f"{func.__module__}.{func.__qualname__}"
                    metric = metric_name or method_name
                    start_time = time.time()
                    
                    # Логирование начала
                    call_manager_func(manager_name, level, f"Executing {method_name}")
                    record_metric_func(f"{metric}.calls")
                    
                    try:
                        result = func(*args, **kwargs)
                        duration = time.time() - start_time
                        
                        # Логирование успеха
                        call_manager_func(manager_name, level, f"{method_name} completed in {duration:.3f}s")
                        record_timing_func(f"{metric}.duration", duration)
                        record_metric_func(f"{metric}.success")
                        
                        return result
                    except Exception as e:
                        duration = time.time() - start_time
                        
                        # Логирование ошибки
                        log_error_func(f"{method_name} failed: {str(e)}")
                        track_error_func(e, {"method": method_name})
                        record_timing_func(f"{metric}.error_duration", duration)
                        record_metric_func(f"{metric}.errors")
                        
                        raise
                
                return wrapper
            return decorator
        
        instance.logged = logged
        instance.timed = timed
        instance.monitored = monitored





