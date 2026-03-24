# -*- coding: utf-8 -*-
"""
BatchManager — буферизация и пакетная запись логов.

Потокобезопасен (threading.Lock): несколько потоков одного процесса могут
одновременно вызывать add_message() и flush_all() без гонок данных.

Принцип: callback вызывается ВНЕ lock-а, чтобы медленная I/O-операция
не блокировала остальные потоки-логгеры.
"""
import time
import threading
from typing import Any, Callable, Dict, List, Deque
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class BatchConfig:
    """Конфигурация батчинга."""
    max_size: int = 100          # Максимальный размер пачки
    flush_interval: float = 1.0  # Интервал принудительного сброса (секунды)
    priority_flush: bool = True  # ERROR/CRITICAL — немедленный сброс


class BatchManager:
    """Потокобезопасный менеджер пакетной записи логов.

    Принцип работы:
      - Сообщения накапливаются в deque по каналу (channel → deque)
      - Сброс происходит по трём триггерам:
        1. priority_flush=True + level in [ERROR, CRITICAL] → немедленно
        2. размер пачки >= max_size
        3. прошло >= flush_interval секунд с последнего сброса
      - flush_callback(channel, batch) вызывается ВНЕ блокировки

    Thread safety:
      _lock защищает batches и last_flush_time.
      flush_callback намеренно вызывается без _lock — I/O не должен
      блокировать поток, который добавляет сообщения.
    """

    def __init__(self, flush_callback: Callable, config: BatchConfig = None) -> None:
        """
        Args:
            flush_callback: fn(channel: str, batch: List[dict]) → None.
                            Вызывается при каждом сбросе пачки.
            config:         Параметры батчинга. По умолчанию BatchConfig().
        """
        self.flush_callback = flush_callback
        self.config = config or BatchConfig()

        self._lock = threading.Lock()
        self.batches: Dict[str, Deque[Dict[str, Any]]] = defaultdict(deque)
        self.last_flush_time: Dict[str, float] = {}
        self.stats: Dict[str, Any] = {
            'total_batches': 0,
            'total_messages': 0,
            'avg_batch_size': 0.0,
        }

    def add_message(self, channel: str, message: Dict[str, Any]) -> None:
        """Добавить запись лога в буфер канала.

        При необходимости (priority_flush, max_size, flush_interval) немедленно
        сбрасывает накопленную пачку через flush_callback.

        Args:
            channel: Имя канала (ключ в batches).
            message: Словарь записи лога (из LogRecord.to_dict()).
        """
        should_flush = False
        flush_reason = None

        with self._lock:
            if channel not in self.last_flush_time:
                self.last_flush_time[channel] = time.time()

            self.batches[channel].append(message)
            self.stats['total_messages'] += 1

            current_size = len(self.batches[channel])
            time_since_flush = time.time() - self.last_flush_time[channel]

            if self.config.priority_flush and message.get('level') in ('ERROR', 'CRITICAL'):
                should_flush = True
                flush_reason = 'priority'
            elif current_size >= self.config.max_size:
                should_flush = True
                flush_reason = 'size'
            elif time_since_flush >= self.config.flush_interval:
                should_flush = True
                flush_reason = 'interval'

        if should_flush:
            self._flush_channel(channel)

    def _flush_channel(self, channel: str) -> None:
        """Сбросить накопленную пачку для одного канала.

        Извлечение пачки атомарно (под _lock).
        Вызов callback — вне _lock (не блокирует add_message других потоков).
        """
        # Атомарно извлекаем пачку
        with self._lock:
            if not self.batches.get(channel):
                return
            batch = list(self.batches[channel])
            self.batches[channel].clear()
            self.last_flush_time[channel] = time.time()

            batch_size = len(batch)
            self.stats['total_batches'] += 1
            n = self.stats['total_batches']
            self.stats['avg_batch_size'] = (
                self.stats['avg_batch_size'] * (n - 1) / n + batch_size / n
            )

        # I/O вне lock — не блокируем других потоков
        try:
            self.flush_callback(channel, batch)
        except Exception as e:
            print(f"[BatchManager] flush failed for '{channel}': {e}")

    def flush_all(self) -> None:
        """Принудительно сбросить все каналы (например, при shutdown).

        Потокобезопасен: список каналов берётся атомарно, каждый канал
        сбрасывается отдельно (lock удерживается только при извлечении).
        """
        with self._lock:
            channels = list(self.batches.keys())
        for channel in channels:
            self._flush_channel(channel)

