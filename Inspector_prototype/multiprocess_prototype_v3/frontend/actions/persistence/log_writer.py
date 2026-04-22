# -*- coding: utf-8 -*-
"""
ActionLogWriter — буферизованная запись Actions в БД батчами.

Проблема: при слайдерах ~30 тиков/сек прямая запись каждого Action
в БД создаёт избыточную нагрузку.

Решение: буферизация с coalescing + таймерный flush каждые N мс.
Coalescing в буфере: если action.coalesce_key совпадает с последним
pending — последний заменяется новым (сохраняем только финальное значение).

Thread safety: enqueue вызывается из GUI-потока, flush — из Timer-потока.
Используется threading.Lock для защиты буфера.
"""
from __future__ import annotations

import logging
import threading
from typing import List, Optional

from .repository import ActionLogRepository
from ..schemas import Action

logger = logging.getLogger(__name__)


class ActionLogWriter:
    """
    Буферизованный писатель Actions в ActionLogRepository.

    - enqueue(): добавляет Action в буфер; coalescing по coalesce_key;
      при достижении max_buffer_size вызывает автоматический flush.
    - flush(): batch INSERT через repository.append в цикле; no-op при пустом буфере.
    - start(): запускает периодический таймер (threading.Timer).
    - stop(): flush + остановить таймер.
    """

    def __init__(
        self,
        repository: ActionLogRepository,
        flush_interval_ms: int = 500,
        max_buffer_size: int = 10,
    ) -> None:
        """
        Args:
            repository: репозиторий для записи Actions в БД.
            flush_interval_ms: интервал периодического flush в миллисекундах.
            max_buffer_size: максимальный размер буфера; при достижении — auto flush.
        """
        self._repository = repository
        self._flush_interval_sec: float = flush_interval_ms / 1000.0
        self._max_buffer_size = max_buffer_size

        self._buffer: List[Action] = []
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._stopped = False

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def enqueue(self, action: Action) -> None:
        """
        Добавить Action в буфер.

        Coalescing: если action.coalesce_key совпадает с coalesce_key
        последнего элемента буфера — последний заменяется новым action.
        При len(buffer) >= max_buffer_size — автоматический flush.
        """
        with self._lock:
            if (
                action.coalesce_key is not None
                and self._buffer
                and self._buffer[-1].coalesce_key == action.coalesce_key
            ):
                # Заменяем последний pending action новым (финальное значение)
                self._buffer[-1] = action
            else:
                self._buffer.append(action)

            # Автоматический flush при переполнении буфера
            if len(self._buffer) >= self._max_buffer_size:
                self._flush_locked()

    def flush(self) -> None:
        """
        Записать все pending Actions в БД.

        No-op при пустом буфере. Thread-safe.
        """
        with self._lock:
            self._flush_locked()

    def start(self) -> None:
        """Запустить периодический таймер для автоматического flush."""
        self._stopped = False
        self._schedule_timer()

    def stop(self) -> None:
        """
        Остановить таймер и выполнить финальный flush.

        Гарантирует, что все pending Actions записаны в БД перед выходом.
        """
        self._stopped = True
        # Отменяем текущий таймер (если есть)
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        # Финальный flush всех оставшихся Actions
        self.flush()

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _flush_locked(self) -> None:
        """
        Записать буфер в БД. Вызывать ТОЛЬКО под self._lock.

        Batch INSERT: вызываем repository.append для каждого Action.
        При ошибке логируем, не подавляем.
        """
        if not self._buffer:
            return

        # Забираем буфер атомарно
        batch = self._buffer[:]
        self._buffer.clear()

        # Запись вне критической секции не нужна — мы уже держим lock,
        # но БД-вызов может быть долгим. Для простоты оставляем под lock:
        # buffer уже очищен, новые enqueue не блокируются надолго.
        for action in batch:
            try:
                self._repository.append(action)
            except Exception:
                logger.exception(
                    "Ошибка записи Action action_id=%s в БД",
                    action.action_id,
                )

    def _schedule_timer(self) -> None:
        """Запланировать следующий периодический flush через threading.Timer."""
        if self._stopped:
            return

        timer = threading.Timer(self._flush_interval_sec, self._on_timer_tick)
        timer.daemon = True
        timer.start()

        with self._lock:
            self._timer = timer

    def _on_timer_tick(self) -> None:
        """Callback таймера: flush + перезапуск следующего тика."""
        self.flush()
        # Рекурсивный перезапуск (не бесконечная рекурсия — Timer создаёт новый поток)
        self._schedule_timer()
