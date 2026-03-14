"""
Мониторинг статуса процессов.

Отвечает за:
- Получение статуса процессов
- Мониторинг состояния
- Статистика процессов
"""

from multiprocessing import Process
from typing import Dict, Any, List, Optional


class ProcessStatus:
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
    
    def get_process_status(self, process_name: str) -> Optional[Dict[str, Any]]:
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
            'processes': self.get_all_status()
        }
    
    def has_alive_processes(self) -> bool:
        """Проверить, есть ли живые процессы"""
        return any(p.is_alive() for p in self.os_processes)
    
    def get_process_names(self) -> List[str]:
        """Получить список имен всех процессов"""
        return [p.name for p in self.os_processes]

