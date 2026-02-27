"""
Конфигурация и типы для потоков-воркеров.
"""

from enum import Enum
from typing import List


class WorkerStatus(Enum):
    """Статусы состояния воркера."""
    STOPPED = "stopped"      # Остановлен
    RUNNING = "running"      # Работает
    ERROR = "error"          # Ошибка выполнения
    STOPPING = "stopping"    # В процессе остановки


class ThreadPriority(Enum):
    """Приоритеты потоков выполнения.
    
    Определяют частоту опроса и важность потока в системе.
    """
    SYSTEM = 0        # Системные потоки (0.001s интервал)
    REALTIME = 1      # Потоки реального времени (0.01s интервал)
    NORMAL = 2        # Обычные потоки (0.1s интервал)
    BATCH = 3         # Пакетная обработка (1.0s интервал)
    BACKGROUND = 4    # Фоновые задачи (5.0s интервал)


class ThreadConfig:
    """Конфигурация потока-воркера.
    
    Содержит параметры для настройки поведения потока:
    приоритет, интервал опроса, перезапуск при ошибках, зависимости.
    
    Attributes:
        priority: Приоритет потока
        poll_interval: Интервал опроса (автоматически вычисляется из приоритета)
        restart_on_failure: Автоматический перезапуск при ошибке
        max_restarts: Максимальное количество перезапусков
        dependencies: Список имен воркеров, от которых зависит этот воркер
    """
    
    def __init__(self, 
                 priority: ThreadPriority = ThreadPriority.NORMAL,
                 restart_on_failure: bool = False,
                 max_restarts: int = 3,
                 dependencies: List[str] = None):
        """
        Инициализация конфигурации потока.
        
        Args:
            priority: Приоритет потока (по умолчанию NORMAL)
            restart_on_failure: Перезапуск при ошибке (по умолчанию False)
            max_restarts: Максимальное количество перезапусков (по умолчанию 3)
            dependencies: Список зависимостей от других воркеров (по умолчанию [])
        """
        self.priority = priority
        self.poll_interval = self._get_poll_interval(priority)
        self.restart_on_failure = restart_on_failure
        self.max_restarts = max_restarts
        self.dependencies = dependencies or []
    
    def _get_poll_interval(self, priority: ThreadPriority) -> float:
        """
        Вычисление интервала опроса на основе приоритета.
        
        Args:
            priority: Приоритет потока
            
        Returns:
            float: Интервал опроса в секундах
        """
        intervals = {
            ThreadPriority.SYSTEM: 0.001,
            ThreadPriority.REALTIME: 0.01,
            ThreadPriority.NORMAL: 0.1,
            ThreadPriority.BATCH: 1.0,
            ThreadPriority.BACKGROUND: 5.0
        }
        return intervals[priority]

