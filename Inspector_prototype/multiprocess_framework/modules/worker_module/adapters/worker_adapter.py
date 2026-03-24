# -*- coding: utf-8 -*-
"""
WorkerAdapter — адаптер WorkerManager для использования внутри ProcessModule.

Роль в архитектуре:
    ProcessModule.worker_manager  →  WorkerAdapter  →  WorkerManager

Адаптер предоставляет:
  - Тонкую обёртку над WorkerManager с контекстом процесса.
  - Удобные методы create_worker / start / stop / list с разумными дефолтами.
  - Агрегированную статистику (адаптер + менеджер).

Что НЕ делает адаптер:
  - Не управляет системными потоками (это зона ProcessModule/SystemThreads).
  - Не знает о каналах и маршрутизации (это зона RouterManager).
"""

from typing import Any, Callable, Dict, List, Optional

from ...base_manager.adapters.base_adapter import BaseAdapter
from ..core.thread_config import ThreadConfig
from ..types import WorkerType, ExecutionMode


class WorkerAdapter(BaseAdapter):
    """Адаптер WorkerManager для интеграции в ProcessModule.

    Создаётся ProcessManagers при инициализации процесса:
        adapter = WorkerAdapter(worker_manager, process=self)
        worker_manager.attach_adapter(adapter, name="process")

    После этого доступен через process.worker_adapter.
    """

    def __init__(self, worker_manager, process: Optional[Any] = None) -> None:
        super().__init__(worker_manager, process, "WorkerAdapter")

    # ---- BaseAdapter lifecycle ----

    def setup(self) -> bool:
        if not self.manager:
            self._log("error", "WorkerManager not set")
            return False
        self._initialized = True
        self._log("info", "WorkerAdapter initialized")
        return True

    # ---- Создание воркеров ----

    def create_worker(
        self,
        name: str,
        target: Callable,
        config: Optional[ThreadConfig] = None,
        auto_start: bool = False,
    ) -> bool:
        """Создать воркер с опциональным ThreadConfig (дефолт: NORMAL/APPLICATION/LOOP)."""
        if not self.manager:
            return False
        effective_config = config if config is not None else ThreadConfig()
        return self.manager.create_worker(name, target, effective_config, auto_start)

    def create_system_worker(
        self,
        name: str,
        target: Callable,
        auto_start: bool = False,
    ) -> bool:
        """Создать системный воркер (SYSTEM priority + WorkerType.SYSTEM)."""
        from ..types import ThreadPriority
        config = ThreadConfig(
            priority=ThreadPriority.SYSTEM,
            worker_type=WorkerType.SYSTEM,
            execution_mode=ExecutionMode.LOOP,
        )
        return self.create_worker(name, target, config, auto_start)

    def create_task_worker(
        self,
        name: str,
        target: Callable,
        auto_start: bool = False,
    ) -> bool:
        """Создать одноразовый воркер (ExecutionMode.TASK)."""
        config = ThreadConfig(execution_mode=ExecutionMode.TASK)
        return self.create_worker(name, target, config, auto_start)

    # ---- Управление ----

    def start_worker(self, name: str) -> bool:
        return self.manager.start_worker(name) if self.manager else False

    def stop_worker(self, name: str, timeout: float = 5.0) -> bool:
        return self.manager.stop_worker(name, timeout) if self.manager else False

    def restart_worker(self, name: str, timeout: float = 5.0) -> bool:
        return self.manager.restart_worker(name, timeout) if self.manager else False

    def pause_worker(self, name: str) -> bool:
        return self.manager.pause_worker(name) if self.manager else False

    def resume_worker(self, name: str) -> bool:
        return self.manager.resume_worker(name) if self.manager else False

    # ---- Мониторинг ----

    def get_status(self, name: str) -> Optional[Dict]:
        return self.manager.get_worker_status(name) if self.manager else None

    def is_running(self, name: str) -> bool:
        return self.manager.is_worker_running(name) if self.manager else False

    def has_worker(self, name: str) -> bool:
        return self.manager.has_worker(name) if self.manager else False

    # ---- Списки ----

    def list_workers(self, worker_type: Optional[WorkerType] = None) -> List[str]:
        if not self.manager:
            return []
        return self.manager.list_workers(worker_type)

    def list_application_workers(self) -> List[str]:
        return self.list_workers(WorkerType.APPLICATION)

    def list_system_workers(self) -> List[str]:
        return self.list_workers(WorkerType.SYSTEM)

    # ---- Статистика ----

    def get_stats(self) -> Dict:
        stats = super().get_stats()
        if self.manager and hasattr(self.manager, "get_stats"):
            try:
                stats["manager"] = self.manager.get_stats()
            except Exception:
                pass
        return stats
