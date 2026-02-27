"""
Windows-специфичная реализация платформенного адаптера.
"""

import sys
import psutil
from multiprocessing import Process, freeze_support, set_start_method
from typing import Dict, Any

from .base import PlatformAdapter


class WindowsPlatform(PlatformAdapter):
    """
    Windows-реализация платформенного адаптера.
    
    Использует:
    - spawn метод для multiprocessing
    - freeze_support для PyInstaller
    - psutil для управления приоритетами
    """
    
    # Маппинг приоритетов для Windows
    PRIORITY_MAP = {
        'high': psutil.HIGH_PRIORITY_CLASS,
        'normal': psutil.NORMAL_PRIORITY_CLASS,
        'low': psutil.IDLE_PRIORITY_CLASS,
        'below_normal': psutil.BELOW_NORMAL_PRIORITY_CLASS,
        'above_normal': psutil.ABOVE_NORMAL_PRIORITY_CLASS,
    }
    
    def __init__(self):
        """Инициализация Windows платформы."""
        self._multiprocessing_setup = False
    
    def setup_multiprocessing(self) -> None:
        """
        Настройка multiprocessing для Windows.
        
        Устанавливает spawn метод и вызывает freeze_support.
        Вызывается только один раз.
        """
        if self._multiprocessing_setup:
            return
        
        if sys.platform == "win32":
            set_start_method('spawn', force=False)
            freeze_support()
        
        self._multiprocessing_setup = True
    
    def get_priority_map(self) -> Dict[str, Any]:
        """
        Получить маппинг приоритетов для Windows.
        
        Returns:
            Словарь приоритетов
        """
        return self.PRIORITY_MAP.copy()
    
    def apply_priority(self, process: Process, priority_name: str) -> bool:
        """
        Применить приоритет к процессу на Windows.
        
        Args:
            process: Процесс ОС
            priority_name: Имя приоритета
            
        Returns:
            True если успешно применен
        """
        priority_value = self.PRIORITY_MAP.get(priority_name, psutil.NORMAL_PRIORITY_CLASS)
        
        try:
            p = psutil.Process(process.pid)
            p.nice(priority_value)
            return True
        except (psutil.AccessDenied, PermissionError):
            # На некоторых системах требуется права администратора
            return False
        except Exception:
            return False

