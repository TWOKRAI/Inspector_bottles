import threading
import queue
import time
from typing import Dict, Any, List, Optional, Callable

class ProcessModule:
    """
    Минимальный базовый класс для всех процессов.
    Только самая основная функциональность.
    """
    
    def __init__(self, name: str = 'Process', 
                 queue_manager = None, 
                 control_queue: Optional[queue.Queue] = None):
        """
        Args:
            name: Имя процесса
            queue_manager: Менеджер очередей
            control_queue: Очередь для управляющих команд
        """
        self.name = name
        self.queue_manager = queue_manager
        self.control_queue = control_queue
        
        # Базовые флаги управления
        self.stop_process = False
        self.threads = []
        
        # Менеджеры будут созданы в дочерних классах
        self.managers = {}
        
        # Инициализация
        self._init_managers()
        self._init_threads()
        
    def _init_managers(self):
        """Инициализация менеджеров - для переопределения"""
        # Дочерние классы будут создавать здесь конкретные менеджеры
        # и добавлять их в self.managers
        pass
        
    def _init_threads(self):
        """Инициализация потоков - для переопределения"""
        # Дочерние классы будут создавать здесь свои потоки
        pass

    def register_thread(self, name: str, target: Callable, daemon: bool = False) -> threading.Thread:
        """Регистрация нового потока"""
        thread = threading.Thread(
            name=f"{self.name}_{name}",
            target=target,
            daemon=daemon
        )
        self.threads.append(thread)
        return thread

    def register_manager(self, name: str, manager):
        """Регистрация менеджера"""
        self.managers[name] = manager

    def run(self):
        """Запуск процесса"""
        print(f"[{self.name}] Starting process")
        
        # Запуск менеджеров
        self._start_managers()
        
        # Запуск потоков
        for thread in self.threads:
            thread.start()
            print(f"[{self.name}] Started thread: {thread.name}")
            
        print(f"[{self.name}] Process started successfully")

    def _start_managers(self):
        """Запуск всех менеджеров"""
        for name, manager in self.managers.items():
            if hasattr(manager, 'start'):
                manager.start()
                print(f"[{self.name}] Started manager: {name}")

    def stop(self):
        """Корректная остановка процесса"""
        print(f"[{self.name}] Stopping process")
        self.stop_process = True
        
        # Остановка менеджеров
        self._stop_managers()
        
        # Остановка потоков
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=5.0)
                if thread.is_alive():
                    print(f"[{self.name}] WARNING: Thread {thread.name} didn't stop in time")
                    
        print(f"[{self.name}] Process stopped")

    def _stop_managers(self):
        """Остановка всех менеджеров"""
        for name, manager in self.managers.items():
            if hasattr(manager, 'stop'):
                try:
                    manager.stop()
                    print(f"[{self.name}] Stopped manager: {name}")
                except Exception as e:
                    print(f"[{self.name}] Error stopping manager {name}: {e}")

    def should_stop(self) -> bool:
        """Проверка условий остановки"""
        return (
            self.stop_process or 
            (self.queue_manager.stop_event.is_set() 
             if self.queue_manager and hasattr(self.queue_manager, 'stop_event') else False)
        )

    def get_manager(self, name: str):
        """Получение менеджера по имени"""
        return self.managers.get(name)

    def main(self):
        """Основная логика процесса (для переопределения)"""
        # Заглушка - в реальном процессе здесь будет основная работа
        time.sleep(0.1)