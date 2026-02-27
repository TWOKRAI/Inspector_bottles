"""
Вспомогательные утилиты для системы логирования.
"""

import time
import inspect
from typing import Callable, Any

def get_caller_module(depth: int = 2) -> str:
    """
    Определяет модуль вызвавшей функции.
    
    Args:
        depth: Глубина в stack frame (2 = caller of caller)
    
    Returns:
        Имя модуля
    """
    frame = inspect.currentframe()
    for _ in range(depth):
        if frame.f_back:
            frame = frame.f_back
    
    module = inspect.getmodule(frame)
    return module.__name__ if module else "unknown"

class Timer:
    """
    Утилита для замера времени выполнения.
    
    Example:
        with Timer() as timer:
            # ваш код
        logger.performance("INFO", f"Operation took {timer.elapsed:.3f}s")
    """
    
    def __init__(self):
        self.elapsed = 0.0
    
    def __enter__(self):
        self.start = time.time()
        return self
    
    def __exit__(self, *args):
        self.elapsed = time.time() - self.start