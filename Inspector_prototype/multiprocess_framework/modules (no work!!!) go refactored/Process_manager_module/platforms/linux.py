"""
Linux-специфичная реализация платформенного адаптера.

TODO: Реализовать для Linux/Raspberry Pi/Jetson
"""

import psutil
from multiprocessing import Process
from typing import Dict, Any

from .base import PlatformAdapter


class LinuxPlatform(PlatformAdapter):
    """
    Linux-реализация платформенного адаптера.
    
    TODO: Реализовать для Linux/Raspberry Pi/Jetson
    Сейчас использует базовую реализацию через psutil.
    """
    
    # Маппинг приоритетов для Unix-систем (nice values)
    # nice: -20 (highest) до 19 (lowest)
    PRIORITY_MAP = {
        'high': -10,        # Высокий приоритет
        'normal': 0,        # Нормальный приоритет
        'low': 10,          # Низкий приоритет
        'below_normal': 5,   # Ниже нормального
        'above_normal': -5,  # Выше нормального
    }
    
    def setup_multiprocessing(self) -> None:
        """
        Настройка multiprocessing для Linux.
        
        На Linux обычно используется fork (по умолчанию).
        TODO: Добавить специфичные настройки для Raspberry Pi/Jetson
        """
        # На Linux fork работает по умолчанию, ничего не делаем
        pass
    
    def get_priority_map(self) -> Dict[str, Any]:
        """
        Получить маппинг приоритетов для Linux.
        
        Returns:
            Словарь приоритетов (nice values)
        """
        return self.PRIORITY_MAP.copy()
    
    def apply_priority(self, process: Process, priority_name: str) -> bool:
        """
        Применить приоритет к процессу на Linux.
        
        Args:
            process: Процесс ОС
            priority_name: Имя приоритета
            
        Returns:
            True если успешно применен
        """
        priority_value = self.PRIORITY_MAP.get(priority_name, 0)
        
        try:
            p = psutil.Process(process.pid)
            p.nice(priority_value)
            return True
        except (psutil.AccessDenied, PermissionError):
            # Может потребоваться права root для высоких приоритетов
            return False
        except Exception:
            return False

