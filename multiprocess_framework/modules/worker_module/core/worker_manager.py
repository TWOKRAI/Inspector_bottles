# -*- coding: utf-8 -*-
"""
Менеджер управления потоками-воркерами.

Реализует IWorkerManager поверх BaseManager + ObservableMixin.
Предоставляет централизованное управление жизненным циклом потоков:
создание, запуск, остановка, пауза, мониторинг, статистика.
"""

import time
from typing import Callable, Dict, List, Optional

from ...base_manager import BaseManager, ObservableMixin

from ..interfaces import IWorkerManager
from ..types import WorkerStatus, WorkerType, ExecutionMode
from .thread_config import ThreadConfig
from ..registry import WorkerRegistry
from ..lifecycle import WorkerLifecycle


class WorkerManager(BaseManager, ObservableMixin, IWorkerManager):
    """Менеджер управления потоками-воркерами.

    Наследуется от BaseManager (жизненный цикл, адаптеры, события) и
    ObservableMixin (логирование, метрики, реестр менеджеров).

    Attributes:
        manager_name: Имя менеджера (используется для именования потоков).
        _worker_registry: Потокобезопасный реестр воркеров.
        _lifecycle: Управление жизненным циклом воркеров.
    """

    def __init__(self, manager_name: str, process=None):
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        ObservableMixin.__init__(self, managers={}, config={}, auto_proxy=True)

        self._worker_registry = WorkerRegistry()
        self._lifecycle = WorkerLifecycle(self)

        # Синоним для совместимости
        self.name = manager_name

    # ========================================================================
    # BaseManager — жизненный цикл
    # ========================================================================

    def initialize(self) -> bool:
        try:
            self.is_initialized = True
            self._log_info(f"WorkerManager '{self.manager_name}' initialized")
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize WorkerManager '{self.manager_name}': {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self.stop_all_workers()
            self.is_initialized = False
            self._log_info(f"WorkerManager '{self.manager_name}' shut down")
            return True
        except Exception as e:
            self._log_error(f"Error during shutdown of WorkerManager '{self.manager_name}': {e}")
            return False

    # ========================================================================
    # Создание и управление воркерами
    # ========================================================================

    def create_worker(
        self,
        worker_name: str,
        target: Callable,
        config: ThreadConfig,
        auto_start: bool = False,
    ) -> bool:
        """Создать воркер. config может быть ThreadConfig или dict (будет десериализован)."""
        if isinstance(config, dict):
            config = ThreadConfig.from_dict(config)

        success = self._lifecycle.create_worker(worker_name, target, config, auto_start)
        if success:
            self._log_info(f"Worker '{worker_name}' created")
        else:
            self._log_warning(f"Failed to create worker '{worker_name}'")
        return success

    def start_worker(self, worker_name: str) -> bool:
        success = self._lifecycle.start_worker(worker_name)
        if success:
            self._log_info(f"Worker '{worker_name}' started")
        return success

    def stop_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        success = self._lifecycle.stop_worker(worker_name, timeout)
        if success:
            self._log_info(f"Worker '{worker_name}' stopped")
        return success

    def restart_worker(self, worker_name: str, timeout: float = 5.0) -> bool:
        success = self._lifecycle.restart_worker(worker_name, timeout)
        if success:
            self._log_info(f"Worker '{worker_name}' restarted")
        return success

    def pause_worker(self, worker_name: str) -> bool:
        worker_info = self._worker_registry.get(worker_name)
        if not worker_info:
            return False
        worker_info["pause_event"].set()
        self._log_info(f"Worker '{worker_name}' paused")
        return True

    def resume_worker(self, worker_name: str) -> bool:
        worker_info = self._worker_registry.get(worker_name)
        if not worker_info:
            return False
        worker_info["pause_event"].clear()
        self._log_info(f"Worker '{worker_name}' resumed")
        return True

    # ========================================================================
    # Групповые операции
    # ========================================================================

    def start_all_workers(self) -> None:
        for name in self._worker_registry.get_all_names():
            self.start_worker(name)
        self._log_info("All workers started")

    def stop_all_workers(self) -> None:
        for name in self._worker_registry.get_all_names():
            self.stop_worker(name)
        self._log_info("All workers stopped")

    def pause_all_workers(self, exclude_system: bool = True) -> None:
        """Поставить на паузу все воркеры.

        Args:
            exclude_system: Если True — НЕ паузить воркеры с типом SYSTEM
                (например heartbeat_sender), иначе ProcessMonitor решит,
                что процесс мёртв из-за отсутствия heartbeat.
        """
        for name in self._worker_registry.get_all_names():
            worker_info = self._worker_registry.get(name)
            if not worker_info:
                continue
            # Пропускаем системные воркеры, если exclude_system=True
            if exclude_system:
                worker_type = worker_info.get("worker_type")
                if worker_type == WorkerType.SYSTEM:
                    self._log_debug(
                        f"Пропуск паузы для системного воркера '{name}' (SYSTEM type)"
                    )
                    continue
            self.pause_worker(name)
        self._log_info("Application workers paused (system workers excluded)")

    def resume_all_workers(self, exclude_system: bool = True) -> None:
        """Возобновить все ранее поставленные на паузу воркеры.

        Args:
            exclude_system: Если True — пропустить воркеры с типом SYSTEM
                (они и не были поставлены на паузу командой pause_all).
        """
        for name in self._worker_registry.get_all_names():
            worker_info = self._worker_registry.get(name)
            if not worker_info:
                continue
            # Пропускаем системные воркеры — они не паузились
            if exclude_system:
                worker_type = worker_info.get("worker_type")
                if worker_type == WorkerType.SYSTEM:
                    self._log_debug(
                        f"Пропуск resume для системного воркера '{name}' (SYSTEM type)"
                    )
                    continue
            self.resume_worker(name)
        self._log_info("Application workers resumed")

    # ========================================================================
    # Мониторинг и статус
    # ========================================================================

    def is_worker_running(self, worker_name: str) -> bool:
        worker_info = self._worker_registry.get(worker_name)
        return bool(worker_info and worker_info["status"] == WorkerStatus.RUNNING)

    def get_worker_status(self, worker_name: str) -> Optional[Dict]:
        worker_info = self._worker_registry.get(worker_name)
        if not worker_info:
            return None
        return {
            "name": worker_name,
            "status": worker_info["status"].value,
            "worker_type": worker_info.get("worker_type", WorkerType.APPLICATION).value,
            "execution_mode": worker_info.get("execution_mode", ExecutionMode.LOOP).value,
            "is_alive": worker_info["thread"].is_alive(),
            "restart_count": worker_info["restart_count"],
            "last_error": worker_info["last_error"],
            "metrics": self.get_worker_metrics(worker_name),
        }

    def get_all_workers_status(self) -> Dict[str, Dict]:
        return {
            name: self.get_worker_status(name)
            for name in self._worker_registry.get_all_names()
        }

    def get_worker_metrics(self, worker_name: str) -> Optional[Dict]:
        worker_info = self._worker_registry.get(worker_name)
        if not worker_info:
            return None

        current_runtime = worker_info["total_runtime"]
        if (
            worker_info["status"] == WorkerStatus.RUNNING
            and worker_info["start_time"] is not None
        ):
            current_runtime += time.time() - worker_info["start_time"]

        total_runs = worker_info["successful_runs"] + worker_info["failed_runs"]
        avg_run_time = current_runtime / total_runs if total_runs > 0 else 0

        return {
            "total_runtime": round(current_runtime, 3),
            "last_run_duration": round(worker_info["last_run_duration"], 3),
            "successful_runs": worker_info["successful_runs"],
            "failed_runs": worker_info["failed_runs"],
            "restart_count": worker_info["restart_count"],
            "avg_run_time": round(avg_run_time, 3),
            "start_time": worker_info["start_time"],
            "uptime": (
                round(time.time() - worker_info["start_time"], 3)
                if worker_info["start_time"]
                else 0
            ),
        }

    # ========================================================================
    # Список воркеров с фильтрацией
    # ========================================================================

    def has_worker(self, worker_name: str) -> bool:
        return self._worker_registry.has(worker_name)

    def list_workers(self, worker_type: Optional[WorkerType] = None) -> List[str]:
        """Получить список воркеров, опционально фильтруя по типу."""
        if worker_type is not None:
            return self._worker_registry.get_by_type(worker_type)
        return self._worker_registry.get_all_names()

    def list_system_workers(self) -> List[str]:
        """Список системных воркеров (WorkerType.SYSTEM)."""
        return self.list_workers(WorkerType.SYSTEM)

    def list_application_workers(self) -> List[str]:
        """Список прикладных воркеров (WorkerType.APPLICATION)."""
        return self.list_workers(WorkerType.APPLICATION)

    # ========================================================================
    # Статистика
    # ========================================================================

    def get_stats(self) -> Dict:
        stats = super().get_stats()
        all_names = self._worker_registry.get_all_names()
        stats.update({
            "workers_count": len(all_names),
            "system_workers": len(self.list_system_workers()),
            "application_workers": len(self.list_application_workers()),
            "running_workers": sum(1 for n in all_names if self.is_worker_running(n)),
            "workers_status": self.get_all_workers_status(),
        })
        return stats
