"""
Реестр воркеров.

Управление регистрацией и хранением информации о воркерах.
"""

import threading
from typing import Dict, Callable, Optional
from datetime import datetime

from ..core.thread_config import ThreadConfig, WorkerStatus


class WorkerRegistry:
    """
    Реестр воркеров.
    
    Инкапсулирует логику регистрации и хранения информации о воркерах.
    """
    
    def __init__(self):
        """Инициализация реестра."""
        self.workers: Dict[str, Dict] = {}
        self.thread_configs: Dict[str, ThreadConfig] = {}
    
    def register(
        self,
        worker_name: str,
        target: Callable,
        config: ThreadConfig,
        thread: threading.Thread,
        stop_event: threading.Event,
        pause_event: threading.Event
    ) -> bool:
        """
        Регистрация воркера в реестре.
        
        Args:
            worker_name: Имя воркера
            target: Целевая функция
            config: Конфигурация потока
            thread: Поток воркера
            stop_event: Событие остановки
            pause_event: Событие паузы
            
        Returns:
            bool: True если регистрация успешна
        """
        if worker_name in self.workers:
            return False
        
        self.workers[worker_name] = {
            'thread': thread,
            'stop_event': stop_event,
            'pause_event': pause_event,
            'target': target,
            'config': config,
            'status': WorkerStatus.STOPPED,
            'restart_count': 0,
            'last_error': None,
            'start_time': None,
            'total_runtime': 0.0,
            'last_run_duration': 0.0,
            'successful_runs': 0,
            'failed_runs': 0,
            'has_been_started': False
        }
        
        self.thread_configs[worker_name] = config
        return True
    
    def unregister(self, worker_name: str) -> bool:
        """
        Удаление воркера из реестра.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            bool: True если удаление успешно
        """
        if worker_name in self.workers:
            del self.workers[worker_name]
            self.thread_configs.pop(worker_name, None)
            return True
        return False
    
    def get(self, worker_name: str) -> Optional[Dict]:
        """
        Получение информации о воркере.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            Dict с информацией о воркере или None
        """
        return self.workers.get(worker_name)
    
    def has(self, worker_name: str) -> bool:
        """
        Проверка наличия воркера.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            bool: True если воркер зарегистрирован
        """
        return worker_name in self.workers
    
    def get_all_names(self) -> list:
        """Получить список имен всех воркеров."""
        return list(self.workers.keys())
    
    def update_status(self, worker_name: str, status: WorkerStatus):
        """
        Обновление статуса воркера.
        
        Args:
            worker_name: Имя воркера
            status: Новый статус
        """
        if worker_name in self.workers:
            self.workers[worker_name]['status'] = status
    
    def get_status(self, worker_name: str) -> Optional[WorkerStatus]:
        """
        Получение статуса воркера.
        
        Args:
            worker_name: Имя воркера
            
        Returns:
            WorkerStatus или None
        """
        worker_info = self.workers.get(worker_name)
        return worker_info['status'] if worker_info else None

