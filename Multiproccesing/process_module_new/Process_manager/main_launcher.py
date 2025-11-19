#!/usr/bin/env python3
"""
Главный запускатель системы процессов
"""
import time
import signal
import sys
from Processes_Manager import ProcessManager

class SystemLauncher:
    def __init__(self):
        self.process_manager = ProcessManager()
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
    
    def initialize_system(self):
        """Инициализация всей системы"""
        print("🚀 Initializing DD Architecture System...")
        
        # Конфигурация системы
        self.process_manager.frontend_enable = True
        self.process_manager.backend_enable = True
        
        # Инициализация процессов
        self.process_manager.initialize_processes()
        
        print("✅ System initialization completed")
    
    def start(self):
        """Запуск системы"""
        print("🎯 Starting all processes...")
        self.process_manager.start_processes()
        
        # Вывод информации о запущенных процессах
        print("\n📊 Running Processes:")
        for i, process in enumerate(self.process_manager.os_processes, 1):
            print(f"  {i}. {process.name} (PID: {process.pid})")
        
        print("\n💡 System is running. Press Ctrl+C to stop.")
    
    def stop(self):
        """Остановка системы"""
        print("\n🛑 Stopping system...")
        self.process_manager.stop_processes()
        print("✅ System stopped")
    
    def wait(self):
        """Ожидание завершения работы"""
        try:
            self.process_manager.wait_for_processes()
        except KeyboardInterrupt:
            self.stop()

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
        launcher.stop()
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)