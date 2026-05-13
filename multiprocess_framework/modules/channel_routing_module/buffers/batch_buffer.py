# -*- coding: utf-8 -*-
"""
BatchBuffer — буферная стратегия с пакетной записью.

Адаптация logger_module/batcher/batch_manager.py к интерфейсу IBufferStrategy.
Подходит для LoggerManager и других менеджеров с требованиями к батчингу.

Принцип:
    enqueue() накапливает данные в deque по каналу.
    Сброс происходит по трём триггерам:
      1. priority_flush=True и priority == "urgent" → немедленно
      2. Размер пачки >= max_size
      3. Прошло >= flush_interval секунд с последнего сброса

    flush_fn(channel: str, batch: List[dict]) вызывается ВНЕ lock-а —
    медленный I/O не блокирует потоки, вызывающие enqueue().

Thread safety:
    _lock защищает batches и last_flush_time.
    Список каналов для flush_all() берётся атомарно.
"""

import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Dict, Deque, List, Optional

from ..interfaces import IBufferStrategy


@dataclass
class BatchConfig:
    """Параметры пакетной буферизации."""

    max_size: int = 100  # Максимальный размер пачки
    flush_interval: float = 1.0  # Интервал принудительного сброса (сек)
    priority_flush: bool = True  # "urgent" priority → немедленный сброс


class BatchBuffer(IBufferStrategy):
    """Потокобезопасная пакетная буферная стратегия.

    Пример использования:
        def _do_flush(channel_name: str, batch: list) -> None:
            ch = registry.get(channel_name)
            for item in batch:
                ch.write(item)

        buf = BatchBuffer(flush_fn=_do_flush, config=BatchConfig(max_size=50))
        buf.start()
        buf.enqueue("logs", {"level": "INFO", "message": "..."})
        buf.flush()   # принудительный сброс всех каналов
        buf.stop()
    """

    def __init__(
        self,
        flush_fn: Callable[[str, List[Dict[str, Any]]], Any],
        config: Optional[BatchConfig] = None,
    ) -> None:
        """
        Args:
            flush_fn: fn(channel_name: str, batch: List[dict]) → Any
                      Вызывается при каждом сбросе пачки (вне lock-а).
            config:   Параметры батчинга. По умолчанию BatchConfig().
        """
        self._flush_fn = flush_fn
        self._config = config or BatchConfig()

        self._lock = threading.Lock()
        self._batches: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        self._last_flush_time: Dict[str, float] = {}

        self._total_enqueued: int = 0
        self._total_batches: int = 0
        self._total_flushed: int = 0
        self._errors: int = 0

        self._timer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # IBufferStrategy — lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Запустить фоновый поток периодического flush."""
        if self._timer_thread and self._timer_thread.is_alive():
            return
        self._stop_event.clear()
        self._timer_thread = threading.Thread(
            target=self._timer_worker,
            name="batch-buffer-timer",
            daemon=True,
        )
        self._timer_thread.start()

    def stop(self) -> None:
        """Остановить фоновый поток и сбросить оставшиеся данные."""
        self._stop_event.set()
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=5.0)
        self._timer_thread = None
        self.flush()

    # ------------------------------------------------------------------
    # IBufferStrategy — enqueue / flush
    # ------------------------------------------------------------------

    def enqueue(
        self,
        channel: str,
        data: Dict[str, Any],
        priority: str = "normal",
    ) -> None:
        """Добавить данные в буфер канала.

        При необходимости (priority_flush, max_size, flush_interval) немедленно
        сбрасывает накопленную пачку.
        """
        should_flush = False

        with self._lock:
            if channel not in self._last_flush_time:
                self._last_flush_time[channel] = time.time()

            self._batches[channel].append(data)
            self._total_enqueued += 1
            current_size = len(self._batches[channel])
            elapsed = time.time() - self._last_flush_time[channel]

            if self._config.priority_flush and priority == "urgent":
                should_flush = True
            elif current_size >= self._config.max_size:
                should_flush = True
            elif elapsed >= self._config.flush_interval:
                should_flush = True

        if should_flush:
            self._flush_channel(channel)

    def flush(self, channel: Optional[str] = None) -> None:
        """Принудительно сбросить буфер.

        channel=None → сбросить все каналы.
        """
        if channel is not None:
            self._flush_channel(channel)
        else:
            self.flush_all()

    def flush_all(self) -> None:
        """Принудительно сбросить все каналы."""
        with self._lock:
            channels = list(self._batches.keys())
        for ch in channels:
            self._flush_channel(ch)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            pending = {ch: len(buf) for ch, buf in self._batches.items()}
        return {
            "type": "batch",
            "total_enqueued": self._total_enqueued,
            "total_batches": self._total_batches,
            "total_flushed": self._total_flushed,
            "errors": self._errors,
            "pending": pending,
            "running": bool(self._timer_thread and self._timer_thread.is_alive()),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush_channel(self, channel: str) -> None:
        """Атомарно извлечь пачку, затем вызвать flush_fn вне lock-а."""
        with self._lock:
            if not self._batches.get(channel):
                return
            batch = list(self._batches[channel])
            self._batches[channel].clear()
            self._last_flush_time[channel] = time.time()
            self._total_batches += 1
            self._total_flushed += len(batch)

        try:
            self._flush_fn(channel, batch)
        except Exception:
            self._errors += 1

    def _timer_worker(self) -> None:
        """Периодически вызывает flush_all() по интервалу."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._config.flush_interval)
            if not self._stop_event.is_set():
                try:
                    self.flush_all()
                except Exception:
                    pass
