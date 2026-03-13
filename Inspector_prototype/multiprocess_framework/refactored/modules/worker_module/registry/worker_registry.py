# -*- coding: utf-8 -*-
"""
Потокобезопасный реестр воркеров.

Все операции защищены threading.Lock.
"""

import threading
from typing import Callable, Dict, List, Optional

from ..interfaces import IWorkerRegistry
from ..types import WorkerStatus, WorkerType, ExecutionMode


class WorkerRegistry(IWorkerRegistry):
    """Потокобезопасный реестр воркеров.

    Хранит WorkerInfo-словари для каждого зарегистрированного воркера.
    Все публичные методы защищены self._lock (threading.Lock).

    Это центральное хранилище информации обо всех потоках, запущенных в ProcessModule.
    Гарантирует целостность данных при одновременном доступе из разных потоков
    и из основного потока WorkerManager.

    Данные:
        _workers: Dict[str, WorkerInfo]
            Словарь имя-воркера → полная информация о воркере (WorkerInfo TypedDict).

    Операции:
        register() — добавить новый воркер (атомарно)
        unregister() — удалить воркер (редко используется)
        get() — получить информацию о воркере
        get_all_names() — получить все имена воркеров
        get_by_type() — фильтр по WorkerType (SYSTEM/APPLICATION)
        update_status() — обновить статус
        get_status() — получить статус

    Thread-safety:
        Все методы используют контекстный менеджер with self._lock:
        для защиты доступа к _workers словарю.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._workers: Dict[str, Dict] = {}

    # ---- Регистрация ----

    def register(
        self,
        worker_name: str,
        target: Callable,
        config,
        thread: threading.Thread,
        stop_event: threading.Event,
        pause_event: threading.Event,
    ) -> bool:
        """Зарегистрировать воркер. Возвращает False если имя уже занято."""
        with self._lock:
            if worker_name in self._workers:
                return False

            self._workers[worker_name] = {
                "thread": thread,
                "stop_event": stop_event,
                "pause_event": pause_event,
                "target": target,
                "config": config,
                "status": WorkerStatus.STOPPED,
                "worker_type": getattr(config, "worker_type", WorkerType.APPLICATION),
                "execution_mode": getattr(config, "execution_mode", ExecutionMode.LOOP),
                "restart_count": 0,
                "last_error": None,
                "start_time": None,
                "total_runtime": 0.0,
                "last_run_duration": 0.0,
                "successful_runs": 0,
                "failed_runs": 0,
                "has_been_started": False,
            }
            return True

    def unregister(self, worker_name: str) -> bool:
        """Удалить воркер из реестра."""
        with self._lock:
            if worker_name in self._workers:
                del self._workers[worker_name]
                return True
            return False

    # ---- Чтение ----

    def get(self, worker_name: str) -> Optional[Dict]:
        """Получить dict воркера (прямая ссылка — мутации допустимы под внешней блокировкой)."""
        with self._lock:
            return self._workers.get(worker_name)

    def has(self, worker_name: str) -> bool:
        with self._lock:
            return worker_name in self._workers

    def get_all_names(self) -> List[str]:
        with self._lock:
            return list(self._workers.keys())

    def get_by_type(self, worker_type: WorkerType) -> List[str]:
        """Получить имена воркеров определённого типа."""
        with self._lock:
            return [
                name for name, info in self._workers.items()
                if info.get("worker_type") == worker_type
            ]

    # ---- Обновление статуса ----

    def update_status(self, worker_name: str, status: WorkerStatus) -> None:
        with self._lock:
            if worker_name in self._workers:
                self._workers[worker_name]["status"] = status

    def get_status(self, worker_name: str) -> Optional[WorkerStatus]:
        with self._lock:
            info = self._workers.get(worker_name)
            return info["status"] if info else None

    # ---- Статистика ----

    def snapshot(self) -> Dict[str, Dict]:
        """Снимок реестра (shallow copy каждого dict)."""
        with self._lock:
            return {name: dict(info) for name, info in self._workers.items()}

    def __len__(self) -> int:
        with self._lock:
            return len(self._workers)
