#!/usr/bin/env python3
"""
Главный запускатель системы процессов.

Предоставляет удобный интерфейс для запуска и управления всей системой процессов.
Использует ProcessManagerBootstrap для запуска ProcessManager.
"""

import sys
import signal
from typing import Optional, Union, Dict, Any
from pathlib import Path

from ..bootstrap import ProcessManagerBootstrap


class SystemLauncher:
    """
    Главный запускатель системы процессов.
    
    Предоставляет удобный интерфейс для:
    - Запуска ProcessManager через ProcessManagerBootstrap
    - Остановки системы
    - Обработки сигналов
    
    Использует новую архитектуру с ProcessManager.
    """
    
    def __init__(
        self,
        config: Optional[Union[str, Path, Dict[str, Any]]] = None,
        bootstrap: Optional[ProcessManagerBootstrap] = None
    ):
        """
        Инициализация запускателя системы.
        
        Args:
            config: Конфигурация процессов (путь к файлу или словарь)
            bootstrap: ProcessManagerBootstrap (если None, создается новый)
        """
        self.bootstrap = bootstrap or ProcessManagerBootstrap(config=config)
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """Настройка обработчиков сигналов для graceful shutdown"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов остановки"""
        print(f"\n🛑 Received signal {signum}, shutting down...")
        self.stop()
        sys.exit(0)
    
    def initialize_system(self, process_config: Optional[Union[str, Path, Dict[str, Any]]] = None):
        """
        Инициализация всей системы.
        
        Примечание: В новой архитектуре инициализация происходит автоматически
        при создании ProcessManagerBootstrap. Этот метод оставлен для обратной совместимости.
        
        Args:
            process_config: Конфигурация процессов (опционально, если не передана в конструктор)
        """
        print("🚀 Initializing DD Architecture System...")
        
        # Если конфиг не был передан в конструктор, создаем новый bootstrap
        if process_config is not None and self.bootstrap.processes_config is None:
            self.bootstrap = ProcessManagerBootstrap(config=process_config)
        
        print("✅ System initialization completed")
    
    def start(self):
        """Запуск системы"""
        print("🎯 Starting ProcessManager...")
        
        success = self.bootstrap.start()
        if not success:
            raise RuntimeError("Failed to start ProcessManager")
        
        # Вывод информации о запущенном ProcessManager
        if self.bootstrap.process_manager_process:
            print(f"\n📊 ProcessManager started:")
            status = "🟢" if self.bootstrap.process_manager_process.is_alive() else "🔴"
            print(f"  {status} {self.bootstrap.process_manager_process.name} (PID: {self.bootstrap.process_manager_process.pid})")
        
        print("\n💡 System is running. Press Ctrl+C to stop.")
    
    def stop(self):
        """Остановка системы"""
        print("\n🛑 Stopping system...")
        self.bootstrap.stop()
        print("✅ System stopped")
    
    def wait(self):
        """Ожидание завершения работы"""
        try:
            self.bootstrap.wait()
        except KeyboardInterrupt:
            self.stop()
    
    def get_status(self) -> dict:
        """
        Получить статус системы.
        
        Returns:
            Dict: Статус ProcessManager и информация о системе
        """
        status = {
            'bootstrap_running': self.bootstrap.is_running(),
            'process_manager_process': None
        }
        
        if self.bootstrap.process_manager_process:
            status['process_manager_process'] = {
                'name': self.bootstrap.process_manager_process.name,
                'pid': self.bootstrap.process_manager_process.pid,
                'is_alive': self.bootstrap.process_manager_process.is_alive()
            }
        
        # Получаем информацию о процессах из shared_resources
        if self.bootstrap.shared_resources:
            registered_processes = list(self.bootstrap.shared_resources.process_state_registry.get_all_processes().keys())
            status['registered_processes'] = registered_processes
        
        return status
    
    def get_stats(self) -> dict:
        """
        Получить статистику системы.
        
        Returns:
            Dict: Полная статистика системы
        """
        stats = {
            'bootstrap': {
                'is_running': self.bootstrap.is_running(),
                'has_process_manager_process': self.bootstrap.process_manager_process is not None
            },
            'shared_resources': {}
        }
        
        # Получаем статистику из shared_resources
        if self.bootstrap.shared_resources:
            try:
                stats['shared_resources'] = self.bootstrap.shared_resources.get_stats()
            except Exception:
                pass
        
        return stats
    

def main():
    """Главная функция запуска"""
    launcher = SystemLauncher()
    
    try:
        # Инициализация и запуск
        launcher.initialize_system()
        launcher.start()
        
        # Основной цикл ожидания
        launcher.wait()
        
    except Exception as e:
        print(f"❌ System error: {e}")
        import traceback
        traceback.print_exc()
        launcher.stop()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

