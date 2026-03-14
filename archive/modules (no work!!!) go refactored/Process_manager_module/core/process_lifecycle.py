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
from typing import List, Dict, Any, Optional

from ...Logger_module import LoggerManager


class ProcessLifecycle:
    """
    Управление жизненным циклом процессов ОС.
    
    Инкапсулирует всю логику запуска, остановки и ожидания процессов.
    """
    
    def __init__(self, stop_event: Event, logger: Optional[LoggerManager] = None):
        """
        Инициализация менеджера жизненного цикла.
        
        Args:
            stop_event: Событие остановки всех процессов
            logger: Менеджер логирования
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
    
    def start_all(self):
        """Запускает все процессы ОС"""
        if self.logger:
            self.logger.info("🚀 Starting all processes...", module="process_lifecycle")
        
        for process in self.os_processes:
            try:
                process.start()
                if self.logger:
                    self.logger.info(f"✅ Started OS process: {process.name} (PID: {process.pid})", module="process_lifecycle")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"❌ Failed to start process {process.name}: {e}", module="process_lifecycle")
    
    def stop_all(self, timeout: float = 3.0):
        """
        Корректно останавливает все процессы.
        
        Args:
            timeout: Таймаут ожидания для каждого процесса в секундах
        """
        if self.logger:
            self.logger.info("🛑 Stopping all processes...", module="process_lifecycle")
        
        # Устанавливаем флаг остановки
        self.stop_event.set()
        
        # Ждем завершения процессов ОС
        self.join_all(timeout)
        
        # Если процессы все еще живы, завершаем принудительно
        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger.warning(f"⚠️ Terminating process {process.name}", module="process_lifecycle")
                try:
                    process.terminate()
                    time.sleep(0.1)
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"⚠️ Error terminating {process.name}: {e}", module="process_lifecycle")
        
        # Финальная проверка
        for process in self.os_processes:
            if process.is_alive():
                if self.logger:
                    self.logger.error(f"❌ Force killing process {process.name}", module="process_lifecycle")
                try:
                    process.kill()
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"❌ Error killing {process.name}: {e}", module="process_lifecycle")
        
        if self.logger:
            self.logger.info("✅ All processes stopped", module="process_lifecycle")
    
    def join_all(self, timeout: float = 3.0):
        """
        Ожидает завершения всех процессов ОС.
        
        Args:
            timeout: Таймаут ожидания для каждого процесса в секундах
        """
        for process in self.os_processes:
            try:
                if self.logger:
                    self.logger.info(f"⏳ Waiting for {process.name} to finish...", module="process_lifecycle")
                process.join(timeout=timeout)
                if process.is_alive():
                    if self.logger:
                        self.logger.warning(f"⚠️ Process {process.name} is still alive after {timeout}s timeout", module="process_lifecycle")
                else:
                    if self.logger:
                        self.logger.info(f"✅ Process {process.name} finished gracefully", module="process_lifecycle")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"❌ Error joining process {process.name}: {e}", module="process_lifecycle")
    
    def wait_for_all(self):
        """Ожидание завершения всех процессов (бесконечно)"""
        try:
            # Ждем бесконечно
            while any(p.is_alive() for p in self.os_processes):
                time.sleep(0.1)
        except KeyboardInterrupt:
            if self.logger:
                self.logger.info("\n🛑 Interrupted by user", module="process_lifecycle")
            self.stop_all()
    
    def get_alive_processes(self) -> List[Process]:
        """Получить список живых процессов"""
        return [p for p in self.os_processes if p.is_alive()]
    
    def get_dead_processes(self) -> List[Process]:
        """Получить список завершенных процессов"""
        return [p for p in self.os_processes if not p.is_alive()]
    
    def get_process_by_name(self, name: str) -> Optional[Process]:
        """
        Получить процесс по имени.
        
        Args:
            name: Имя процесса
        
        Returns:
            Процесс или None если не найден
        """
        for process in self.os_processes:
            if process.name == name:
                return process
        return None

