"""ChainThreadPool — публичный пул параллельного исполнения шагов бандла.

C6(e): реализация переведена на ``WorkerPoolExecutor`` (пул поверх worker_module,
единый механизм потоков фреймворка) — собственного поток-пула из stdlib больше
нет. Публичный контракт (``submit_bundle``/``collect_results``/``resize``/
``step_timeout``/``max_workers``) не изменился: ``ParallelChainRunnable`` и
существующие тесты работают без правок.
"""

from __future__ import annotations

from typing import Any

from .worker_pool_executor import WorkerPoolExecutor


class ChainThreadPool(WorkerPoolExecutor):
    """Пул параллельного исполнения шагов бандла (поверх worker_module).

    Тонкий фасад над :class:`WorkerPoolExecutor` — сохраняет публичное имя и
    контракт прежнего ChainThreadPool. Каждый шаг бандла получает ``frame.copy()``
    и исполняется одним из ``max_workers`` персистентных LOOP-воркеров.

    Args:
        max_workers: Количество рабочих потоков пула.
        step_timeout: Максимальное время ожидания одного шага (секунды).
        logger: LoggerManager или любой ObservableMixin-совместимый объект.
    """

    def __init__(
        self,
        max_workers: int = 2,
        step_timeout: float = 10.0,
        logger: Any = None,
    ) -> None:
        super().__init__(
            max_workers=max_workers,
            step_timeout=step_timeout,
            logger=logger,
            manager_name="ChainThreadPool",
        )


__all__ = ["ChainThreadPool"]
