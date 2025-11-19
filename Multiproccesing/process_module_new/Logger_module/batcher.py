"""
Менеджер пачек для группировки логов.
Улучшает производительность при массовой записи.
"""

import time
import threading
from typing import Dict, List, Callable, Deque
from collections import defaultdict, deque
from dataclasses import dataclass
from config import LogLevel

@dataclass
class BatchConfig:
    """Конфигурация батчинга"""
    max_size: int = 100
    flush_interval: float = 1.0  # секунды
    priority_flush: bool = True  # Быстрая обработка ERROR и CRITICAL

class BatchManager:
    """
    Управляет формированием и сбросом пачек логов.
    """
    
    def __init__(self, flush_callback: Callable, config: BatchConfig = None):
        self.flush_callback = flush_callback
        self.config = config or BatchConfig()
        
        self.batches: Dict[str, Deque[Dict]] = defaultdict(deque)
        self.timers: Dict[str, threading.Timer] = {}
        self.lock = threading.RLock()
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
        with self.lock:
            # Инициализация пачки для канала
            if channel not in self.batches:
                self.batches[channel] = deque()
                self._start_timer(channel)
            
            # Добавляем сообщение
            self.batches[channel].append(message)
            self.stats['total_messages'] += 1
            
            # Проверяем условия сброса
            current_size = len(self.batches[channel])
            
            # Приоритетный сброс для ошибок
            if (self.config.priority_flush and 
                message.get('level') in ['ERROR', 'CRITICAL']):
                self._flush_channel(channel)
            # Сброс по размеру
            elif current_size >= self.config.max_size:
                self._flush_channel(channel)
    
    def _start_timer(self, channel: str):
        """Запускает таймер для сброса пачки по времени"""
        def timer_callback():
            self._flush_channel(channel)
        
        # Отменяем предыдущий таймер
        if channel in self.timers:
            self.timers[channel].cancel()
        
        # Создаем новый
        timer = threading.Timer(self.config.flush_interval, timer_callback)
        timer.daemon = True
        timer.start()
        self.timers[channel] = timer
    
    def _flush_channel(self, channel: str):
        """Сбрасывает пачку для канала"""
        with self.lock:
            if channel not in self.batches or not self.batches[channel]:
                return
            
            # Извлекаем пачку
            batch = list(self.batches[channel])
            self.batches[channel].clear()
            
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
            
            # Перезапускаем таймер
            self._start_timer(channel)
    
    def flush_all(self):
        """Принудительно сбрасывает все пачки"""
        with self.lock:
            for channel in list(self.batches.keys()):
                self._flush_channel(channel)
            
            # Останавливаем все таймеры
            for timer in self.timers.values():
                timer.cancel()
            self.timers.clear()