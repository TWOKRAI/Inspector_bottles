"""
Менеджер пачек для группировки логов.
Улучшает производительность при массовой записи.
Без блокировок для совместимости с multiprocessing.
"""

import time
from typing import Dict, List, Callable, Deque
from collections import defaultdict, deque
from dataclasses import dataclass
from ..Logger_module.config import LogLevel

@dataclass
class BatchConfig:
    """Конфигурация батчинга"""
    max_size: int = 100
    flush_interval: float = 1.0  # секунды
    priority_flush: bool = True  # Быстрая обработка ERROR и CRITICAL

class BatchManager:
    """
    Управляет формированием и сбросом пачек логов.
    Без блокировок для совместимости с multiprocessing.
    """
    
    def __init__(self, flush_callback: Callable, config: BatchConfig = None):
        self.flush_callback = flush_callback
        self.config = config or BatchConfig()
        
        self.batches: Dict[str, Deque[Dict]] = defaultdict(deque)
        # Время последнего flush для каждого канала (для проверки интервала)
        self.last_flush_time: Dict[str, float] = {}
        self.stats = {
            'total_batches': 0,
            'total_messages': 0,
            'avg_batch_size': 0.0
        }
    
    def add_message(self, channel: str, message: Dict):
        """
        Добавляет сообщение в пачку.
        
        Args:
            channel: Канал для записи
            message: Сообщение лога
        """
        # Инициализация пачки для канала
        if channel not in self.batches:
            self.batches[channel] = deque()
            self.last_flush_time[channel] = time.time()
        
        # Добавляем сообщение
        self.batches[channel].append(message)
        self.stats['total_messages'] += 1
        
        # Проверяем условия сброса
        current_size = len(self.batches[channel])
        current_time = time.time()
        time_since_flush = current_time - self.last_flush_time.get(channel, current_time)
        
        # Приоритетный сброс для ошибок
        if (self.config.priority_flush and 
            message.get('level') in ['ERROR', 'CRITICAL']):
            self._flush_channel(channel)
        # Сброс по размеру
        elif current_size >= self.config.max_size:
            self._flush_channel(channel)
        # Сброс по времени (проверяем при каждом добавлении)
        elif time_since_flush >= self.config.flush_interval:
            self._flush_channel(channel)
    
    def _flush_channel(self, channel: str):
        """Сбрасывает пачку для канала"""
        if channel not in self.batches or not self.batches[channel]:
            return
        
        # Извлекаем пачку
        batch = list(self.batches[channel])
        self.batches[channel].clear()
        
        # Обновляем время последнего flush
        self.last_flush_time[channel] = time.time()
        
        # Обновляем статистику
        batch_size = len(batch)
        self.stats['total_batches'] += 1
        self.stats['avg_batch_size'] = (
            (self.stats['avg_batch_size'] * (self.stats['total_batches'] - 1) + batch_size) /
            self.stats['total_batches']
        )
        
        # Вызываем колбэк
        try:
            self.flush_callback(channel, batch)
        except Exception as e:
            print(f"Batch flush failed for {channel}: {e}")
    
    def flush_all(self):
        """Принудительно сбрасывает все пачки"""
        for channel in list(self.batches.keys()):
            self._flush_channel(channel)