# -*- coding: utf-8 -*-
"""
Конфигурация потока-воркера.

ThreadConfig описывает параметры запуска потока: приоритет, режим выполнения,
тип воркера и политику перезапуска.

Поддерживает Dict at Boundary через to_dict() / from_dict().
"""

from typing import List, Optional

from ..types import ThreadPriority, WorkerType, ExecutionMode

# Реэкспорт для обратной совместимости (старый код импортирует WorkerStatus из этого модуля)
from ..types import WorkerStatus

__all__ = [
    "ThreadConfig",
    "ThreadPriority",
    "WorkerType",
    "ExecutionMode",
    "WorkerStatus",
]

_POLL_INTERVALS = {
    ThreadPriority.SYSTEM:     0.001,
    ThreadPriority.REALTIME:   0.01,
    ThreadPriority.NORMAL:     0.1,
    ThreadPriority.BATCH:      1.0,
    ThreadPriority.BACKGROUND: 5.0,
}


class ThreadConfig:
    """Конфигурация потока-воркера.

    Описывает параметры запуска потока: приоритет, режим выполнения, тип воркера
    и политику обработки ошибок. Поддерживает Dict at Boundary через to_dict()/from_dict().

    Attributes:
        priority: ThreadPriority
            Приоритет потока. Влияет на poll_interval для проверки stop_event.
            - SYSTEM (0.001s) — критичные системные потоки
            - REALTIME (0.01s) — требует низкой задержки
            - NORMAL (0.1s) — стандартные воркеры (по умолчанию)
            - BATCH (1.0s) — фоновая пакетная обработка
            - BACKGROUND (5.0s) — редко используемое

        poll_interval: float
            Интервал опроса stop_event в секундах (вычисляется из priority).
            Используется в loop-режиме для контроля частоты проверки stop_event.

        restart_on_failure: bool
            Автоматически перезапускать воркер при исключении? (по умолчанию False)

        max_restarts: int
            Максимальное число автоматических перезапусков (по умолчанию 3).
            После max_restarts ошибок воркер остановится с статусом ERROR.

        dependencies: List[str]
            Имена воркеров, которые должны быть запущены раньше этого.
            Используется при create_worker(..., auto_start=True).

        worker_type: WorkerType
            - SYSTEM — внутренний механизм фреймворка (message_processor и т.д.)
            - APPLICATION — пользовательская задача (по умолчанию)

        execution_mode: ExecutionMode
            - LOOP — воркер выполняется в бесконечном цикле, ждёт stop_event (по умолчанию)
            - TASK — воркер выполняется один раз и завершается (статус COMPLETED)

    Example:
        config = ThreadConfig(
            priority=ThreadPriority.NORMAL,
            restart_on_failure=True,
            max_restarts=3,
            worker_type=WorkerType.APPLICATION,
            execution_mode=ExecutionMode.LOOP,
        )

    Dict at Boundary:
        ThreadConfig поддерживает сериализацию для передачи конфигов через границу процессов:

        # Сохранить в словарь (для конфига процесса)
        config_dict = config.to_dict()
        # → {
        #     "priority": "NORMAL",
        #     "restart_on_failure": False,
        #     "max_restarts": 3,
        #     "dependencies": [],
        #     "worker_type": "application",
        #     "execution_mode": "loop",
        # }

        # Восстановить из словаря
        config = ThreadConfig.from_dict(config_dict)
    """

    def __init__(
        self,
        priority: ThreadPriority = ThreadPriority.NORMAL,
        restart_on_failure: bool = False,
        max_restarts: int = 3,
        dependencies: Optional[List[str]] = None,
        worker_type: WorkerType = WorkerType.APPLICATION,
        execution_mode: ExecutionMode = ExecutionMode.LOOP,
    ):
        self.priority = priority
        self.poll_interval = _POLL_INTERVALS[priority]
        self.restart_on_failure = restart_on_failure
        self.max_restarts = max_restarts
        self.dependencies = dependencies or []
        self.worker_type = worker_type
        self.execution_mode = execution_mode

    # ---- Dict at Boundary ----

    def to_dict(self) -> dict:
        """Сериализация для передачи через границу процессов."""
        return {
            "priority": self.priority.name,
            "restart_on_failure": self.restart_on_failure,
            "max_restarts": self.max_restarts,
            "dependencies": list(self.dependencies),
            "worker_type": self.worker_type.value,
            "execution_mode": self.execution_mode.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ThreadConfig":
        """Десериализация из dict (из конфига воркера или через границу процессов)."""
        return cls(
            priority=ThreadPriority[data.get("priority", "NORMAL")],
            restart_on_failure=data.get("restart_on_failure", False),
            max_restarts=data.get("max_restarts", 3),
            dependencies=data.get("dependencies"),
            worker_type=WorkerType(data.get("worker_type", WorkerType.APPLICATION.value)),
            execution_mode=ExecutionMode(data.get("execution_mode", ExecutionMode.LOOP.value)),
        )

    def __repr__(self) -> str:
        return (
            f"ThreadConfig(priority={self.priority.name}, "
            f"worker_type={self.worker_type.value}, "
            f"execution_mode={self.execution_mode.value}, "
            f"restart_on_failure={self.restart_on_failure})"
        )
