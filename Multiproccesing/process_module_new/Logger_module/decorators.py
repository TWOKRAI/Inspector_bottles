"""
Декораторы для удобного логирования.
"""

import time
import functools
from typing import Callable, Any, Optional

from config import LogScope, LogLevel
from manager import get_logger

def log_call(
    scope: LogScope = LogScope.BUSINESS,
    level: LogLevel = LogLevel.INFO,
    log_args: bool = False,
    log_result: bool = False,
    log_time: bool = True
):
    """
    Декоратор для логирования вызовов функций.
    
    Args:
        scope: Область логирования
        level: Уровень логирования
        log_args: Логировать аргументы функции
        log_result: Логировать результат
        log_time: Логировать время выполнения
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger()
            if not logger:
                return func(*args, **kwargs)
            
            module = func.__module__
            func_name = func.__name__
            
            # Логируем начало
            start_msg = f"START: {func_name}"
            if log_args:
                start_msg += f" | args: {args}, kwargs: {kwargs}"
            
            logger.log(scope, level, start_msg, module)
            
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                # Логируем завершение
                end_msg = f"END: {func_name}"
                if log_time:
                    end_msg += f" | time: {duration:.3f}s"
                if log_result:
                    end_msg += f" | result: {result}"
                
                logger.log(scope, level, end_msg, module)
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                error_msg = f"ERROR: {func_name} -> {e}"
                if log_time:
                    error_msg += f" | time: {duration:.3f}s"
                
                logger.log(scope, LogLevel.ERROR, error_msg, module)
                raise
        
        return wrapper
    return decorator


def log_performance(threshold: float = 1.0, scope: LogScope = LogScope.PERFORMANCE):
    """
    Декоратор для логирования медленных функций.
    
    Args:
        threshold: Порог в секундах, после которого функция считается медленной
        scope: Область логирования
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger()
            start_time = time.time()
            
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            
            if logger and duration > threshold:
                logger.log(
                    scope, 
                    LogLevel.WARNING,
                    f"Slow function: {func.__name__} took {duration:.3f}s",
                    func.__module__
                )
            
            return result
        return wrapper
    return decorator


class log_context:
    """
    Контекстный менеджер для логирования с дополнительным контекстом.
    
    Example:
        with log_context(user_id=123, request_id="abc"):
            logger.info("Processing request")
    """
    
    def __init__(self, **context_vars):
        self.context_vars = context_vars
        self.logger = get_logger()
    
    def __enter__(self):
        if self.logger:
            self.logger.push_context(**self.context_vars)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.logger:
            self.logger.pop_context()