# -*- coding: utf-8 -*-
"""
worker_module — менеджер управления потоками-воркерами.

Централизованное управление жизненным циклом потоков внутри ProcessModule:
создание, запуск, остановка, пауза, мониторинг, статистика.

Поддерживает:
    - Два типа потоков: SYSTEM (внутренний механизм) и APPLICATION (пользовательский).
    - Два режима выполнения: LOOP (бесконечный цикл) и TASK (одноразовое).
    - Потокобезопасный реестр (threading.Lock).
    - Dict at Boundary для конфигурации.
    - Автоматический перезапуск при ошибке.
    - Полная метрика и мониторинг.

Публичный API: импортируй только отсюда.

Главные компоненты:
    
    WorkerManager — менеджер потоков.
        Наследуется от BaseManager + ObservableMixin.
        Реализует IWorkerManager.
        Использует WorkerRegistry (потокобезопасный) и WorkerLifecycle (create/start/stop).
        
        Основные методы:
            create_worker(name, target, config, auto_start=False) -> bool
            start_worker(name) -> bool
            stop_worker(name, timeout=5.0) -> bool
            restart_worker(name, timeout=5.0) -> bool
            pause_worker(name) / resume_worker(name)
            get_worker_status(name) -> Optional[Dict]
            list_workers(worker_type=None) -> List[str]
            get_stats() -> Dict
    
    ThreadConfig — конфигурация потока.
        Параметры: priority, restart_on_failure, max_restarts, dependencies,
                   worker_type, execution_mode.
        Dict at Boundary через to_dict() и from_dict().
    
    WorkerAdapter — удобный адаптер для использования из процесса.
        Наследуется от BaseAdapter.
        Делегирует вызовы к WorkerManager.
    
    WorkerSchemaAdapter — извлечение настроек потока из SchemaBase-конфигов.
        Интегрируется с data_schema_module.

Типы:
    
    WorkerStatus: STOPPED, RUNNING, ERROR, STOPPING, COMPLETED
        LOOP воркер → STOPPED при остановке.
        TASK воркер → COMPLETED при успешном завершении.
    
    ThreadPriority: SYSTEM, REALTIME, NORMAL, BATCH, BACKGROUND
        Влияет на poll_interval для stop_event (0.001s, 0.01s, 0.1s, 1.0s, 5.0s).
    
    WorkerType: SYSTEM, APPLICATION
        Различение системных потоков (фреймворк) и пользовательских.
    
    ExecutionMode: LOOP, TASK
        LOOP — бесконечный цикл.
        TASK — одноразовое выполнение.
    
    WorkerInfo: TypedDict со всей информацией о воркере.

Интерфейсы (для зависимостей):
    
    IWorkerManager — главный контракт менеджера.
    IWorkerLifecycle — контракт управления жизненным циклом.
    IWorkerRegistry — контракт реестра воркеров.

Пример использования:

    from multiprocess_framework.modules.worker_module import (
        WorkerManager, ThreadConfig, ThreadPriority, WorkerType, ExecutionMode
    )
    
    def my_worker(stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            process_data()
            time.sleep(1.0)
    
    manager = WorkerManager("my_process")
    manager.initialize()
    
    config = ThreadConfig(
        priority=ThreadPriority.NORMAL,
        worker_type=WorkerType.APPLICATION,
        execution_mode=ExecutionMode.LOOP,
    )
    manager.create_worker("worker_1", my_worker, config, auto_start=True)
    
    status = manager.get_worker_status("worker_1")
    print(f"Status: {status['status']}")  # → "running"
    
    manager.stop_worker("worker_1", timeout=5.0)
    manager.shutdown()

Документация:
    README.md — подробное руководство с примерами.
    ARCHITECTURE.md — дизайн, граф состояний, интеграция.
    STATUS.md — карточка здоровья и статус рефакторинга.
"""

from .core.worker_manager import WorkerManager
from .core.thread_config import ThreadConfig

from .types import WorkerStatus, ThreadPriority, WorkerType, ExecutionMode, WorkerInfo

from .interfaces import IWorkerManager, IWorkerLifecycle, IWorkerRegistry

from .adapters.worker_adapter import WorkerAdapter
from .adapters.schema_adapter import WorkerSchemaAdapter
from .configs import ThreadWorkerConfig, WorkerManagerConfig

__all__ = [
    # Менеджер
    "WorkerManager",
    # Конфигурация
    "ThreadConfig",
    # Типы
    "WorkerStatus",
    "ThreadPriority",
    "WorkerType",
    "ExecutionMode",
    "WorkerInfo",
    # Интерфейсы
    "IWorkerManager",
    "IWorkerLifecycle",
    "IWorkerRegistry",
    # Адаптеры
    "WorkerAdapter",
    "WorkerSchemaAdapter",
    "ThreadWorkerConfig",
    "WorkerManagerConfig",
]
