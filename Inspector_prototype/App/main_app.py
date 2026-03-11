# main.py
# -*- coding: utf-8 -*-
"""
Entry point для приложения App Inspector.

Ответственность:
  - Создание multiprocessing infrastructure (queue_manager, stop_event)
  - Создание и запуск ApplicationCoordinator
  - Graceful shutdown на исключениях

НЕ делает:
  - Не создаёт окна напрямую (Coordinator)
  - Не управляет потоками (Coordinator)
  - Не знает про бизнес-логику
"""

import sys
import signal
from pathlib import Path

# Добавляем корень проекта в путь (если нужно)
# sys.path.insert(0, str(Path(__file__).parent))

# Multiprocessing infrastructure (создаётся здесь, передаётся в Coordinator)
try:
    from multiprocess_framework.refactored.modules.queue_manager import QueueManager
    _HAS_FRAMEWORK = True
except ImportError:
    _HAS_FRAMEWORK = False
    print("WARNING: multiprocess_framework not found, running in mock mode")
    
    # Mock для тестирования без фреймворка
    class MockQueueManager:
        def __init__(self):
            import threading
            self.stop_event = threading.Event()
            self.display_queue = []
            self.camera_to_app = []
            self.process_ready_queue = []
            self.memory_manager = MockMemoryManager()
        
        class MockMemoryManager:
            def read_images(self, name, index):
                return []
            def close_all(self):
                pass
    
    class MockEvent:
        def __init__(self):
            self._set = False
        def is_set(self):
            return self._set
        def set(self):
            self._set = True


def setup_signal_handlers(coordinator):
    """Настройка обработчиков сигналов для graceful shutdown."""
    
    def signal_handler(signum, frame):
        print(f"\n[Main] Received signal {signum}, shutting down...")
        coordinator.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # kill
    
    # Windows: также обрабатываем Ctrl+Break
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, signal_handler)


def create_app(queue_manager, stop_event):
    """
    Создание и запуск приложения (для process_app).
    Вызывается из Multiproccesing.Processes.process_app.
    """
    from App.Core.Application.coordinator import ApplicationCoordinator
    from pathlib import Path

    coordinator = ApplicationCoordinator(
        queue_manager=queue_manager,
        stop_event=stop_event,
        config_path=Path("App/Data/config.yaml"),
    )
    if not coordinator.initialize():
        print("[create_app] Failed to initialize")
        return 1
    try:
        return coordinator.run()
    except Exception as e:
        print(f"[create_app] Error: {e}")
        coordinator.shutdown()
        return 1


def main():
    """
    Главная функция приложения.
    
    Flow:
      1. Создать infrastructure (queues, events)
      2. Создать ApplicationCoordinator
      3. Инициализировать все слои
      4. Запустить главный цикл
      5. Graceful shutdown при выходе
    """
    
    print("=" * 60)
    print("App Inspector Starting...")
    print("=" * 60)
    
    # ═════════════════════════════════════════════════════════════════
    # 1. Создание infrastructure (вне Coordinator!)
    # ═════════════════════════════════════════════════════════════════
    
    if _HAS_FRAMEWORK:
        # Реальный режим с фреймворком
        queue_manager = QueueManager()
        stop_event = queue_manager.stop_event
    else:
        # Mock режим для тестирования
        queue_manager = MockQueueManager()
        stop_event = queue_manager.stop_event
    
    # ═════════════════════════════════════════════════════════════════
    # 2. Создание Coordinator (все слои внутри!)
    # ═════════════════════════════════════════════════════════════════
    
    from App.Core.Application.coordinator import ApplicationCoordinator
    
    coordinator = ApplicationCoordinator(
        queue_manager=queue_manager,
        stop_event=stop_event,
        config_path=Path("App/Data/config.yaml"),
    )
    
    # ═════════════════════════════════════════════════════════════════
    # 3. Инициализация (создание всех слоёв)
    # ═════════════════════════════════════════════════════════════════
    
    if not coordinator.initialize():
        print("[Main] Failed to initialize, exiting.")
        return 1
    
    print("[Main] Initialization complete.")
    
    # ═════════════════════════════════════════════════════════════════
    # 4. Настройка signal handlers
    # ═════════════════════════════════════════════════════════════════
    
    setup_signal_handlers(coordinator)
    
    # ═════════════════════════════════════════════════════════════════
    # 5. Запуск главного цикла (блокирующий!)
    # ═════════════════════════════════════════════════════════════════
    
    try:
        exit_code = coordinator.run()
        print(f"[Main] Exited with code {exit_code}")
        return exit_code
        
    except Exception as e:
        print(f"[Main] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        
        # Пытаемся корректно завершить
        coordinator.shutdown()
        return 1


# ═════════════════════════════════════════════════════════════════════
# Альтернативный entry point: контекстный менеджер (для тестов)
# ═════════════════════════════════════════════════════════════════════

def run_with_context():
    """
    Запуск с автоматическим cleanup (для тестов и скриптов).
    
    Usage:
        with application_context() as coordinator:
            # do something
            pass  # auto-shutdown on exit
    """
    from contextlib import contextmanager
    
    @contextmanager
    def application_context():
        if _HAS_FRAMEWORK:
            queue_manager = QueueManager()
        else:
            queue_manager = MockQueueManager()
        
        from App.Core.Application.coordinator import ApplicationCoordinator
        
        coordinator = ApplicationCoordinator(
            queue_manager=queue_manager,
            stop_event=queue_manager.stop_event,
        )
        
        coordinator.initialize()
        
        try:
            yield coordinator
        finally:
            coordinator.shutdown()
    
    return application_context()


# ═════════════════════════════════════════════════════════════════════
# Точка входа
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Проверка: не запущен ли уже
    # (опционально — проверка на single instance)
    
    sys.exit(main())