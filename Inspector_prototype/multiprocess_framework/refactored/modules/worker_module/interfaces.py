# -*- coding: utf-8 -*-
"""
Публичные контракты worker_module.

Единственный файл, от которого должны зависеть внешние модули.
Внутренние компоненты модуля используют относительные импорты.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from .types import WorkerStatus, WorkerType, ExecutionMode


class IWorkerRegistry(ABC):
    """Контракт реестра воркеров."""

    @abstractmethod
    def register(
        self,
        worker_name: str,
        target: Callable,
        config: Any,
        thread: Any,
        stop_event: Any,
        pause_event: Any,
    ) -> bool: ...

    @abstractmethod
    def unregister(self, worker_name: str) -> bool: ...

    @abstractmethod
    def get(self, worker_name: str) -> Optional[Dict]: ...

    @abstractmethod
    def has(self, worker_name: str) -> bool: ...

    @abstractmethod
    def get_all_names(self) -> List[str]: ...

    @abstractmethod
    def get_by_type(self, worker_type: WorkerType) -> List[str]: ...

    @abstractmethod
    def update_status(self, worker_name: str, status: WorkerStatus) -> None: ...

    @abstractmethod
    def get_status(self, worker_name: str) -> Optional[WorkerStatus]: ...


class IWorkerLifecycle(ABC):
    """Контракт управления жизненным циклом воркеров."""

    @abstractmethod
    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: Any,
        auto_start: bool = False,
    ) -> bool: ...

    @abstractmethod
    def start_worker(self, worker_name: str) -> bool: ...

    @abstractmethod
    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool: ...

    @abstractmethod
    def restart_worker(self, worker_name: str, timeout: float = 5.0) -> bool: ...


class IWorkerManager(ABC):
    """Контракт менеджера потоков.

    Реализуется WorkerManager. Внешние модули (process_module, adapters)
    должны зависеть только от этого интерфейса для обеспечения инверсии зависимостей.

    Методы разделены на категории:
        - Жизненный цикл: initialize/shutdown
        - Создание и управление: create/start/stop/restart/pause/resume
        - Групповые операции: start_all/stop_all
        - Мониторинг: get_status, get_metrics, is_running, has_worker
        - Фильтрация: list_workers (с опциональной фильтрацией по типу)
        - Статистика: get_stats

    Потокобезопасность:
        Все методы потокобезопасны благодаря WorkerRegistry._lock.
        Можно безопасно вызывать из разных потоков одновременно.

    Dict at Boundary:
        create_worker() принимает config как ThreadConfig или dict.
        get_worker_status() возвращает dict, не объект.
    """

    # ---- Жизненный цикл ----

    @abstractmethod
    def initialize(self) -> bool: ...

    @abstractmethod
    def shutdown(self) -> bool: ...

    # ---- Создание и управление ----

    @abstractmethod
    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: Any,
        auto_start: bool = False,
    ) -> bool: ...

    @abstractmethod
    def start_worker(self, worker_name: str) -> bool: ...

    @abstractmethod
    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool: ...

    @abstractmethod
    def restart_worker(self, worker_name: str, timeout: float = 5.0) -> bool: ...

    @abstractmethod
    def pause_worker(self, worker_name: str) -> bool: ...

    @abstractmethod
    def resume_worker(self, worker_name: str) -> bool: ...

    # ---- Групповые операции ----

    @abstractmethod
    def start_all_workers(self) -> None: ...

    @abstractmethod
    def stop_all_workers(self) -> None: ...

    # ---- Мониторинг ----

    @abstractmethod
    def get_worker_status(self, worker_name: str) -> Optional[Dict]: ...

    @abstractmethod
    def get_all_workers_status(self) -> Dict[str, Dict]: ...

    @abstractmethod
    def get_worker_metrics(self, worker_name: str) -> Optional[Dict]: ...

    @abstractmethod
    def is_worker_running(self, worker_name: str) -> bool: ...

    @abstractmethod
    def has_worker(self, worker_name: str) -> bool: ...

    @abstractmethod
    def list_workers(self, worker_type: Optional[WorkerType] = None) -> List[str]: ...

    # ---- Статистика ----

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]: ...
