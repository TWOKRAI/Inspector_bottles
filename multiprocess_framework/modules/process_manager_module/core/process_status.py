"""
Мониторинг статуса процессов.

Отвечает за:
- Получение статуса процессов
- Мониторинг состояния
- Статистика процессов

Примечание (ADR-117): класс переименован в ProcessStatusMonitor,
чтобы не конфликтовать с ProcessStatus enum из base_manager.
ProcessStatus остаётся как алиас для backward compat.
"""

from multiprocessing import Process
from typing import Dict, Any, List


class ProcessStatusMonitor:
    """
    Мониторинг статуса процессов.

    Инкапсулирует логику получения и мониторинга статуса процессов.
    """
    
    def __init__(self, os_processes: List[Process]):
        """
        Инициализация мониторинга статуса.
        
        Args:
            os_processes: Список процессов ОС для мониторинга
        """
        self.os_processes = os_processes
    
    def get_process_status(self, process_name: str) -> Dict[str, Any]:
        """
        Получить статус конкретного процесса.
        
        Args:
            process_name: Имя процесса
            
        Returns:
            Статус процесса или None если не найден
        """
        for process in self.os_processes:
            if process.name == process_name:
                return self._get_status(process)
        return None
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Получить статус всех процессов.
        
        Returns:
            Словарь статусов процессов
        """
        status = {}
        for process in self.os_processes:
            status[process.name] = self._get_status(process)
        return status
    
    def _get_status(self, process: Process) -> Dict[str, Any]:
        """
        Получить статус процесса.
        
        Args:
            process: Процесс ОС
            
        Returns:
            Словарь со статусом
        """
        return {
            'alive': process.is_alive(),
            'pid': process.pid if process.is_alive() else None,
            'exitcode': process.exitcode,
            'name': process.name
        }
    
    def get_alive_count(self) -> int:
        """Получить количество живых процессов"""
        return sum(1 for p in self.os_processes if p.is_alive())
    
    def get_dead_count(self) -> int:
        """Получить количество завершенных процессов"""
        return sum(1 for p in self.os_processes if not p.is_alive())
    
    def get_total_count(self) -> int:
        """Получить общее количество процессов"""
        return len(self.os_processes)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику процессов.
        
        Returns:
            Словарь со статистикой
        """
        alive = self.get_alive_count()
        dead = self.get_dead_count()
        total = self.get_total_count()
        
        return {
            'total': total,
            'alive': alive,
            'dead': dead,
            'alive_percent': round((alive / total * 100) if total > 0 else 0, 2)
        }


# Backward compat: алиас для кода, импортирующего ProcessStatus из этого модуля.
# В будущем перейти на ProcessStatusMonitor (ADR-117).
ProcessStatus = ProcessStatusMonitor

