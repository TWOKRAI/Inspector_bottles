"""
Управление жизненным циклом процессов ОС.

Отвечает за:
- Запуск процессов
- Остановку процессов
- Ожидание завершения
- Graceful shutdown
"""

import time
from multiprocessing import Process, Event
from typing import List, Optional


class ProcessLifecycle:
    """
    Управление жизненным циклом процессов ОС.
    
    Инкапсулирует всю логику запуска, остановки и ожидания процессов.
    """
    
    def __init__(self, stop_event: Event, logger=None):
        """
        Инициализация менеджера жизненного цикла.
        
        Args:
            stop_event: Событие остановки всех процессов
            logger: Менеджер логирования (опционально)
        """
        self.stop_event = stop_event
        self.logger = logger
        self.os_processes: List[Process] = []
    
    def add_process(self, process: Process):
        """
        Добавить процесс в список для управления.
        
        Args:
            process: Процесс ОС для добавления
        """
        self.os_processes.append(process)
    
    def get_process_by_name(self, name: str) -> Optional[Process]:
        """
        Получить процесс по имени.
        
        Args:
            name: Имя процесса
            
        Returns:
            Process или None если не найден
        """
        for process in self.os_processes:
            if process.name == name:
                return process
        return None
    
    def start_all(self):
        """Запускает все процессы ОС"""
        if self.logger:
            self.logger._log_info("Starting all processes...")
        
        for process in self.os_processes:
            try:
                process.start()
                if self.logger:
                    self.logger._log_info(f"Started OS process: {process.name} (PID: {process.pid})")
            except Exception as e:
                if self.logger:
                    self.logger._log_error(f"Failed to start process {process.name}: {e}")
    
    def stop_all(self, timeout: float = 3.0):
        """
        Корректно останавливает все процессы.
        
        Args:
            timeout: Таймаут ожидания для каждого процесса в секундах
        """
        if self.logger:
            self.logger._log_info("Stopping all processes...")
        
        # Устанавливаем флаг остановки
        self.stop_event.set()
        
        # Ждем завершения процессов ОС
        self.join_all(timeout)
        
        # Если процессы все еще живы, завершаем принудительно
        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger._log_warning(f"Terminating process {process.name}")
                try:
                    process.terminate()
                    time.sleep(0.1)
                except Exception as e:
                    if self.logger:
                        self.logger._log_warning(f"Error terminating {process.name}: {e}")
        
        # Финальная проверка
        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger._log_error(f"Force killing process {process.name}")
                try:
                    process.kill()
                except Exception as e:
                    if self.logger:
                        self.logger._log_error(f"Error killing {process.name}: {e}")
        
        if self.logger:
            self.logger._log_info("All processes stopped")
    
    def join_all(self, timeout: float = 3.0):
        """
        Ожидает завершения всех процессов.
        
        Args:
            timeout: Таймаут ожидания для каждого процесса
        """
        for process in self.os_processes:
            if process.is_alive():
                process.join(timeout=timeout)

