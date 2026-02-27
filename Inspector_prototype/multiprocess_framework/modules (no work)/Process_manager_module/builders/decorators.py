"""
Декораторы для декларативного определения процессов, воркеров и очередей.

Предоставляют удобный способ определения процессов через декораторы,
аналогично Django моделям или Flask маршрутам.

Пример использования:
    from ...Process_manager_module.builders import process, worker, queue
    
    @process(name="ChatProcess", priority="normal")
    class ChatProcess(ProcessModule):
        @worker(name="message_handler", priority="normal")
        def handle_messages(self):
            # Логика обработки сообщений
            pass
        
        @queue(name="custom_queue", maxsize=100)
        def setup_custom_queue(self):
            # Настройка кастомной очереди
            pass
"""

from typing import Dict, Any, Optional, Callable
from functools import wraps


# Глобальный реестр декорированных классов
_DECORATED_PROCESSES: Dict[str, Dict[str, Any]] = {}


def process(
    name: Optional[str] = None,
    priority: str = "normal",
    enabled: bool = True,
    **kwargs
):
    """
    Декоратор для декларативного определения процесса.
    
    Сохраняет метаданные процесса в атрибутах класса для последующей регистрации.
    
    Args:
        name: Имя процесса (если None, используется имя класса)
        priority: Приоритет процесса (high, normal, low, above_normal, below_normal)
        enabled: Включен ли процесс
        **kwargs: Дополнительные параметры конфигурации (queues, workers, console и т.д.)
    
    Пример:
        @process(name="MyProcess", priority="high")
        class MyProcess(ProcessModule):
            pass
    """
    def decorator(cls):
        # Определяем имя процесса
        process_name = name or cls.__name__
        
        # Получаем полный путь к классу
        module_path = cls.__module__
        class_name = cls.__name__
        class_path = f"{module_path}.{class_name}"
        
        # Сохраняем метаданные в классе
        cls._process_metadata = {
            "name": process_name,
            "class_path": class_path,
            "priority": priority,
            "enabled": enabled,
            **kwargs
        }
        
        # Регистрируем в глобальном реестре
        _DECORATED_PROCESSES[process_name] = cls._process_metadata
        
        return cls
    
    return decorator


def worker(
    name: Optional[str] = None,
    priority: str = "normal",
    auto_start: bool = True,
    config: Optional[Dict[str, Any]] = None
):
    """
    Декоратор для декларативного определения воркера процесса.
    
    Сохраняет метаданные воркера в атрибутах метода для последующей регистрации.
    
    Args:
        name: Имя воркера (если None, используется имя метода)
        priority: Приоритет воркера (normal, high, low, realtime, batch)
        auto_start: Автоматически запускать воркер при старте процесса
        config: Дополнительная конфигурация воркера
    
    Пример:
        @worker(name="data_processor", priority="normal")
        def process_data(self):
            # Логика обработки данных
            pass
    """
    def decorator(func: Callable):
        worker_name = name or func.__name__
        
        # Сохраняем метаданные в функции
        func._worker_metadata = {
            "name": worker_name,
            "priority": priority,
            "auto_start": auto_start,
            "config": config or {},
            "function": func
        }
        
        return func
    
    return decorator


def queue(
    name: Optional[str] = None,
    maxsize: int = 100
):
    """
    Декоратор для декларативного определения очереди процесса.
    
    Сохраняет метаданные очереди в атрибутах метода для последующей регистрации.
    
    Args:
        name: Имя очереди (если None, используется имя метода)
        maxsize: Максимальный размер очереди
    
    Пример:
        @queue(name="custom_queue", maxsize=100)
        def setup_custom_queue(self):
            # Настройка кастомной очереди
            pass
    """
    def decorator(func: Callable):
        queue_name = name or func.__name__
        
        # Сохраняем метаданные в функции
        func._queue_metadata = {
            "name": queue_name,
            "maxsize": maxsize
        }
        
        return func
    
    return decorator


def get_decorated_processes() -> Dict[str, Dict[str, Any]]:
    """
    Получить все декорированные процессы из глобального реестра.
    
    Returns:
        Словарь метаданных процессов {process_name: metadata}
    """
    return _DECORATED_PROCESSES.copy()


def get_process_metadata(process_class) -> Optional[Dict[str, Any]]:
    """
    Получить метаданные процесса из декорированного класса.
    
    Args:
        process_class: Класс процесса, декорированный @process
    
    Returns:
        Словарь метаданных или None если класс не декорирован
    """
    return getattr(process_class, '_process_metadata', None)


def get_worker_metadata(worker_func: Callable) -> Optional[Dict[str, Any]]:
    """
    Получить метаданные воркера из декорированной функции.
    
    Args:
        worker_func: Функция воркера, декорированная @worker
    
    Returns:
        Словарь метаданных или None если функция не декорирована
    """
    return getattr(worker_func, '_worker_metadata', None)


def get_queue_metadata(queue_func: Callable) -> Optional[Dict[str, Any]]:
    """
    Получить метаданные очереди из декорированной функции.
    
    Args:
        queue_func: Функция настройки очереди, декорированная @queue
    
    Returns:
        Словарь метаданных или None если функция не декорирована
    """
    return getattr(queue_func, '_queue_metadata', None)

