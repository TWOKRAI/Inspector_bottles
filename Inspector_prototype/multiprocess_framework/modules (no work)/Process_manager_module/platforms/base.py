"""
Базовые абстракции для платформо-зависимых операций.
"""

from typing import Protocol, Dict, Any
from multiprocessing import Process


class PlatformAdapter(Protocol):
    """
    Абстракция для платформо-зависимых операций управления процессами.
    
    Каждая платформа (Windows, Linux, etc.) должна реализовать этот интерфейс.
    """
    
    def setup_multiprocessing(self) -> None:
        """
        Настройка multiprocessing для платформы.
        Вызывается один раз при инициализации системы.
        """
        ...
    
    def get_priority_map(self) -> Dict[str, Any]:
        """
        Получить маппинг приоритетов для платформы.
        
        Returns:
            Словарь: имя_приоритета -> системное_значение
        """
        ...
    
    def apply_priority(self, process: Process, priority_name: str) -> bool:
        """
        Применить приоритет к процессу.
        
        Args:
            process: Процесс ОС
            priority_name: Имя приоритета (high, normal, low, etc.)
            
        Returns:
            True если успешно применен
        """
        ...



class StubPlatformAdapter:
    """Заглушка для тестов или неподдерживаемых платформ."""
    def setup_multiprocessing(self) -> None:
        pass
    
    def get_priority_map(self) -> Dict[str, Any]:
        return {'normal': 0}
    
    def apply_priority(self, process: Process, priority_name: str) -> bool:
        return False  