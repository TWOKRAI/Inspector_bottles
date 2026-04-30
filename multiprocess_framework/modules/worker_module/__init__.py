# -*- coding: utf-8 -*-
"""
worker_module — менеджер жизненного цикла потоков-воркеров.

Централизованное управление потоками внутри ProcessModule:
создание, запуск, остановка, пауза, мониторинг, перезапуск.

Ключевые компоненты:
    WorkerManager — менеджер (BaseManager + ObservableMixin + IWorkerManager)
    ThreadConfig  — конфигурация потока (Dict at Boundary через to_dict/from_dict)
    WorkerAdapter — адаптер для ProcessModule
    WorkerSchemaAdapter — извлечение настроек из SchemaBase

Типы: WorkerStatus, ThreadPriority, WorkerType, ExecutionMode, WorkerInfo
Интерфейсы: IWorkerManager, IWorkerLifecycle, IWorkerRegistry
SchemaBase-конфиги: ThreadWorkerConfig, WorkerManagerConfig
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
