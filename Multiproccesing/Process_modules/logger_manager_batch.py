import logging
import logging.handlers
import time
import asyncio
import threading
from typing import Dict, List, Any, Optional, Callable, Set, DefaultDict
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict
import queue
import heapq

from module_message import CommandMessage, SystemMessage, MessageType, MessageFactory, LogMessage


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogGroup:
    name: str
    file_path: Path
    levels: Set[LogLevel] = field(default_factory=lambda: {LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL})
    modules: Set[str] = field(default_factory=set)
    enabled: bool = True
    max_file_size: int = 10 * 1024 * 1024
    backup_count: int = 5
    batch_interval: float = 1.0  # Интервал батчинга в секундах
    batch_size: int = 100  # Максимальный размер батча


    # Добавляем в LogGroup метод should_log
    def should_log(self, level: LogLevel, module: str) -> bool:
        """Проверка, должен ли лог быть записан в эту группу"""
        return (level in self.levels and 
                (not self.modules or module in self.modules))


class AdaptiveBatcher:
    """
    Адаптивный батчер для группировки логов.
    Автоматически регулирует параметры батчинга в зависимости от нагрузки.
    """
    
    def __init__(self):
        self.batches: DefaultDict[str, List[Dict]] = defaultdict(list)
        self.batch_timers: Dict[str, threading.Timer] = {}
        self.last_flush_time: Dict[str, float] = {}
        self.message_count: Dict[str, int] = defaultdict(int)
        
        # Адаптивные настройки
        self.adaptive_intervals: Dict[str, float] = {}
        self.adaptive_sizes: Dict[str, int] = {}
        
        # Статистика
        self.stats = {
            'total_batches': 0,
            'total_messages': 0,
            'avg_batch_size': 0,
            'avg_flush_time': 0
        }
    
    def add_message(self, group_name: str, message: Dict, group_config: LogGroup):
        """Добавление сообщения в батч с адаптивным управлением"""
        batch_key = f"{group_name}_{id(group_config)}"
        
        # Инициализация адаптивных настроек
        if batch_key not in self.adaptive_intervals:
            self.adaptive_intervals[batch_key] = group_config.batch_interval
            self.adaptive_sizes[batch_key] = group_config.batch_size
        
        # Добавляем сообщение в батч
        self.batches[batch_key].append(message)
        self.message_count[batch_key] += 1
        self.stats['total_messages'] += 1
        
        current_batch_size = len(self.batches[batch_key])
        current_interval = self.adaptive_intervals[batch_key]
        
        # Проверяем условия для сброса батча
        should_flush = (
            current_batch_size >= self.adaptive_sizes[batch_key] or  # Достигли размера
            (time.time() - self.last_flush_time.get(batch_key, 0)) >= current_interval  # Достигли интервала
        )
        
        if should_flush:
            self.flush_batch(batch_key)
        else:
            # Запускаем/перезапускаем таймер, если он еще не активен
            self._start_flush_timer(batch_key, current_interval)
    
    def _start_flush_timer(self, batch_key: str, interval: float):
        """Запуск таймера для сброса батча"""
        # Отменяем предыдущий таймер
        if batch_key in self.batch_timers:
            self.batch_timers[batch_key].cancel()
        
        # Создаем новый таймер
        timer = threading.Timer(interval, self.flush_batch, [batch_key])
        timer.daemon = True
        timer.start()
        self.batch_timers[batch_key] = timer
    
    def flush_batch(self, batch_key: str):
        """Сброс батча и адаптация параметров"""
        if not self.batches[batch_key]:
            return
        
        batch = self.batches[batch_key]
        batch_size = len(batch)
        
        # Сортируем по времени (на случай, если сообщения пришли в неправильном порядке)
        batch.sort(key=lambda x: x['timestamp'])
        
        # Здесь будет вызов колбэка для записи батча
        if hasattr(self, 'flush_callback'):
            start_time = time.time()
            self.flush_callback(batch_key, batch)
            flush_time = time.time() - start_time
            
            # Обновляем статистику
            self.stats['total_batches'] += 1
            self.stats['avg_batch_size'] = (
                (self.stats['avg_batch_size'] * (self.stats['total_batches'] - 1) + batch_size) / 
                self.stats['total_batches']
            )
            self.stats['avg_flush_time'] = (
                (self.stats['avg_flush_time'] * (self.stats['total_batches'] - 1) + flush_time) / 
                self.stats['total_batches']
            )
        
        # Адаптируем параметры на основе нагрузки
        self._adapt_parameters(batch_key, batch_size)
        
        # Очищаем батч
        self.batches[batch_key] = []
        self.last_flush_time[batch_key] = time.time()
        
        # Отменяем таймер
        if batch_key in self.batch_timers:
            self.batch_timers[batch_key].cancel()
            del self.batch_timers[batch_key]
    
    def _adapt_parameters(self, batch_key: str, batch_size: int):
        """Адаптация параметров батчинга на основе нагрузки"""
        current_interval = self.adaptive_intervals[batch_key]
        current_size = self.adaptive_sizes[batch_key]
        
        # Если батч заполняется быстро - увеличиваем интервал и размер
        if batch_size >= current_size * 0.8:  # Батч почти полный
            new_interval = min(current_interval * 1.2, 5.0)  # Макс 5 секунд
            new_size = min(current_size * 1.1, 1000)  # Макс 1000 сообщений
            
            self.adaptive_intervals[batch_key] = new_interval
            self.adaptive_sizes[batch_key] = new_size
        
        # Если батч маленький - уменьшаем параметры для уменьшения задержки
        elif batch_size < current_size * 0.3 and current_interval > 0.1:
            new_interval = max(current_interval * 0.8, 0.1)  # Мин 0.1 секунды
            new_size = max(int(current_size * 0.9), 10)  # Мин 10 сообщений
            
            self.adaptive_intervals[batch_key] = new_interval
            self.adaptive_sizes[batch_key] = new_size
    
    def flush_all(self):
        """Принудительный сброс всех батчей (при остановке)"""
        for batch_key in list(self.batches.keys()):
            if self.batches[batch_key]:
                self.flush_batch(batch_key)
        
        # Отменяем все таймеры
        for timer in self.batch_timers.values():
            timer.cancel()
        self.batch_timers.clear()

class LoggerManager:
    """
    Оптимизированный роутер логов с адаптивным батчингом.
    """
    
    def __init__(self, 
                 base_log_dir: str = "logs",
                 default_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                 enable_batching: bool = True,
                 max_queue_size: int = 10000):
        
        self.base_log_dir = Path(base_log_dir)
        self.base_log_dir.mkdir(exist_ok=True)
        
        self.default_format = default_format
        self.enable_batching = enable_batching

        # Группы и обработчики
        self.groups: Dict[str, LogGroup] = {}
        self.handlers: Dict[str, logging.Handler] = {}
        
        # Очередь и батчер
        self.log_queue = queue.Queue(maxsize=max_queue_size)
        self.batcher = AdaptiveBatcher() if enable_batching else None
        
        if self.batcher:
            self.batcher.flush_callback = self._write_batch
        
        # Статистика
        self.stats = {
            'messages_processed': 0,
            'messages_batched': 0,
            'batches_written': 0,
            'queue_size': 0
        }
    
    def add_group(self, group: LogGroup) -> bool:
        """Добавление группы с настройками батчинга"""
        try:
            group.file_path.parent.mkdir(parents=True, exist_ok=True)
            
            handler = logging.handlers.RotatingFileHandler(
                filename=group.file_path,
                maxBytes=group.max_file_size,
                backupCount=group.backup_count,
                encoding='utf-8'
            )
            
            formatter = logging.Formatter(self.default_format)
            handler.setFormatter(formatter)
            handler.setLevel(logging.DEBUG)
            
            self.groups[group.name] = group
            self.handlers[group.name] = handler
            
            return True
            
        except Exception as e:
            print(f"Failed to add group {group.name}: {e}")
            return False
    
    def route_log(self, level: LogLevel, message: str, module: str = "main"):
        """Маршрутизация лога с учетом батчинга"""
        
        log_record = {
            'timestamp': time.time(),
            'level': level,
            'message': message,
            'module': module
        }
        
        try:
            self.log_queue.put_nowait(log_record)
            self.stats['messages_processed'] += 1
        except queue.Full:
            # При переполнении очереди пишем синхронно
            self._process_log_immediately(log_record)
    
    def _process_log_immediately(self, record: Dict):
        """Немедленная обработка лога (при переполнении очереди)"""
        for group_name, group in self.groups.items():
            if group.should_log(record['level'], record['module']):
                self._write_single_log(group_name, record)
    
    def _route_to_groups(self, record: Dict):
        """Маршрутизация записи в соответствующие группы"""
        for group_name, group in self.groups.items():
            if group.should_log(record['level'], record['module']):
                if self.enable_batching:
                    # Добавляем в батчер
                    self.batcher.add_message(group_name, record, group)
                    self.stats['messages_batched'] += 1
                else:
                    # Немедленная запись
                    self._write_single_log(group_name, record)
    
    def _write_single_log(self, group_name: str, record: Dict):
        """Запись одиночного лога"""
        try:
            log_record = logging.LogRecord(
                name=record['module'],
                level=getattr(logging, record['level'].value),
                pathname='',
                lineno=0,
                msg=record['message'],
                args=(),
                exc_info=None
            )
            log_record.created = record['timestamp']
            
            handler = self.handlers[group_name]
            handler.emit(log_record)
            
        except Exception as e:
            print(f"Failed to write log: {e}")
    
    def _write_batch(self, group_name: str, batch: List[Dict]):
        """Запись батча логов в файл"""
        if not batch:
            return
        
        try:
            handler = self.handlers[group_name]
            
            # Сортируем по времени (на всякий случай)
            batch.sort(key=lambda x: x['timestamp'])
            
            # Формируем одну большую строку для записи
            log_lines = []
            for record in batch:
                log_record = logging.LogRecord(
                    name=record['module'],
                    level=getattr(logging, record['level'].value),
                    pathname='',
                    lineno=0,
                    msg=record['message'],
                    args=(),
                    exc_info=None
                )
                log_record.created = record['timestamp']
                
                # Форматируем запись
                formatted = handler.format(log_record)
                log_lines.append(formatted)
            
            # Записываем все одной операцией
            log_content = "\n".join(log_lines) + "\n"
            
            # Используем низкоуровневую запись для эффективности
            if hasattr(handler, 'stream'):
                handler.stream.write(log_content)
                handler.stream.flush()
            
            self.stats['batches_written'] += 1
            
        except Exception as e:
            print(f"Failed to write batch: {e}")
    
    def _writer_worker(self):
        """Отдельный поток для записи (если нужен)"""
        # В данной реализации запись происходит в основном потоке
        # но можно вынести в отдельный для дополнительной оптимизации
        pass
  
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Получение статистики производительности"""
        base_stats = {
            'messages_processed': self.stats['messages_processed'],
            'queue_size': self.stats['queue_size'],
            'batches_written': self.stats.get('batches_written', 0),
            'batching_enabled': self.enable_batching
        }
        
        if self.batcher:
            base_stats.update({
                'messages_batched': self.stats['messages_batched'],
                'total_batches': self.batcher.stats['total_batches'],
                'avg_batch_size': self.batcher.stats['avg_batch_size'],
                'avg_flush_time': self.batcher.stats['avg_flush_time'],
                'adaptive_intervals': self.batcher.adaptive_intervals,
                'adaptive_sizes': self.batcher.adaptive_sizes
            })
        
        return base_stats

    def process_logs(self, stop_event, pause_event):
        """WorkerManager будет запускать этот метод в потоке"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
        try:
            record = self.log_queue.get_nowait()
            self._route_to_groups(record)
        except queue.Empty:
            time.sleep(0.01)

    def process_log_messages(self, stop_event, pause_event):
        """Обработка лог-сообщений из SystemMessage"""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
                
            # Можно добавить входную очередь для лог-сообщений
            # Пока используем старый метод для совместимости
            time.sleep(0.01)   

    # Добавляем метод для обработки LogMessage
    def handle_log_message(self, log_message: LogMessage):
        """Обработка LogMessage"""
        if log_message.msg_type != MessageType.LOG:
            return
            
        level_name = log_message.log_level.upper()
        try:
            level = LogLevel[level_name]
            self.route_log(level, log_message.log_message, log_message.sender)
        except KeyError:
            # Если уровень не распознан, используем INFO
            self.route_log(LogLevel.INFO, log_message.log_message, log_message.sender)



if __name__ == "__main__":    
# Пример использования с разными стратегиями батчинга
    def setup_optimized_logging():
        """Настройка логирования с разными стратегиями батчинга для разных групп"""
        
        router = LoggerManager(
            base_log_dir="logs/optimized",
            enable_batching=True
        )
        
        # Группа для ошибок - минимальная задержка
        error_group = LogGroup(
            name="errors",
            file_path=Path("logs/optimized/errors.log"),
            levels={LogLevel.ERROR, LogLevel.CRITICAL},
            batch_interval=0.1,  # Быстрый сброс
            batch_size=10        # Маленькие батчи
        )
        
        # Группа для дебага - можно накапливать дольше
        debug_group = LogGroup(
            name="debug",
            file_path=Path("logs/optimized/debug.log"),
            levels={LogLevel.DEBUG},
            batch_interval=2.0,  # Медленный сброс
            batch_size=500       # Большие батчи
        )
        
        # Группа для основной информации - баланс
        info_group = LogGroup(
            name="info",
            file_path=Path("logs/optimized/info.log"),
            levels={LogLevel.INFO, LogLevel.WARNING},
            batch_interval=1.0,
            batch_size=100
        )
        
        router.add_group(error_group)
        router.add_group(debug_group)
        router.add_group(info_group)
        
        router.start()
        return router

    # Тестирование производительности
    def performance_test():
        """Тест производительности с батчингом и без"""
        import random
        
        router = setup_optimized_logging()
        
        # Генерируем нагрузку
        modules = ["camera", "network", "database", "ui", "processing"]
        levels = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR]
        
        start_time = time.time()
        message_count = 10000
        
        for i in range(message_count):
            module = random.choice(modules)
            level = random.choice(levels)
            router.route_log(level, f"Test message {i}", module)
            
            # Имитируем разную нагрузку
            if i % 1000 == 0:
                time.sleep(0.01)
        
        # Даем время на обработку
        time.sleep(2)
        
        stats = router.get_performance_stats()
        total_time = time.time() - start_time
        
        print(f"Обработано {message_count} сообщений за {total_time:.2f} секунд")
        print(f"Скорость: {message_count/total_time:.0f} сообщений/сек")
        print(f"Статистика: {stats}")
        
        router.stop()


    performance_test()