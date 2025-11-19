"""
Основной менеджер логирования.
Объединяет все компоненты в единую систему.
"""

import time
import threading
from typing import Dict, List, Any, Optional
from contextvars import ContextVar

from config import LogConfig, LogLevel, LogScope, ScopeConfig
from dispatcher import LogDispatcher, LogRecord
from batcher import BatchManager, BatchConfig
from channels import create_channel, LogChannel

# Глобальная переменная для контекста (поддерживает асинхронность)
log_context: ContextVar[Dict[str, Any]] = ContextVar('log_context', default={})

class LoggerManager:
    """
    Главный менеджер системы логирования.
    
    Features:
    - Гибкая конфигурация через YAML
    - Множественные каналы записи
    - Батчинг для производительности
    - Контекстное логирование
    - Фильтрация по областям и модулям
    """
    
    _instance = None
    
    def __init__(self, config: LogConfig):
        self.config = config
        self.app_name = config.app_name
        
        # Инициализация компонентов
        self.dispatcher = LogDispatcher(app_name=config.app_name)
        self.batcher = None
        self.channels: Dict[str, LogChannel] = {}
        
        # Контекст логирования
        self._context_stack: List[Dict[str, Any]] = []
        self._context_lock = threading.RLock()
        
        # Кэш для быстрых проверок
        self._decision_cache: Dict[str, bool] = {}
        
        # Статистика
        self.stats = {
            'messages_processed': 0,
            'messages_skipped': 0,
            'messages_batched': 0
        }
        
        # Настройка системы
        self._setup_channels()
        self._setup_batcher()
        
        # Сохраняем инстанс для глобального доступа
        LoggerManager._instance = self
    
    def _setup_channels(self):
        """Настраивает каналы записи"""
        for channel_name, channel_config in self.config.channels.items():
            if channel_config.enabled:
                try:
                    channel = create_channel(channel_config)
                    self.channels[channel_name] = channel
                    
                    # Регистрируем обработчик в диспетчере
                    self.dispatcher.register_channel_handler(
                        channel_name,
                        channel.write
                    )
                except Exception as e:
                    print(f"Failed to setup channel {channel_name}: {e}")
    
    def _setup_batcher(self):
        """Настраивает батчинг если включен"""
        if self.config.enable_batching:
            batch_config = BatchConfig(
                max_size=self.config.batch_size,
                flush_interval=self.config.batch_interval
            )
            self.batcher = BatchManager(self._flush_batch, batch_config)
    
    def _flush_batch(self, channel: str, batch: List[Dict]):
        """Обрабатывает пачку логов"""
        for record in batch:
            self.dispatcher.route_log(
                LogRecord(**record), 
                [channel]
            )
    
    def should_log(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        """
        Определяет, нужно ли логировать сообщение.
        Использует кэш для производительности.
        """
        cache_key = f"{scope.value}:{level.value}:{module}"
        
        if cache_key in self._decision_cache:
            return self._decision_cache[cache_key]
        
        scope_config = self.config.get_scope_config(scope)
        should_log = scope_config.should_log(level, module)
        
        self._decision_cache[cache_key] = should_log
        return should_log
    
    def log(
        self,
        scope: LogScope,
        level: LogLevel,
        message: str,
        module: str = "main",
        **extra
    ):
        """
        Основной метод логирования.
        
        Args:
            scope: Область логирования (система, бизнес и т.д.)
            level: Уровень важности
            message: Текст сообщения
            module: Модуль/компонент источника
            **extra: Дополнительные данные для контекста
        """
        self.stats['messages_processed'] += 1
        
        # Быстрая проверка - нужно ли логировать?
        if not self.should_log(scope, level, module):
            self.stats['messages_skipped'] += 1
            return
        
        # Получаем конфигурацию области
        scope_config = self.config.get_scope_config(scope)
        channels = scope_config.channels or list(self.channels.keys())
        
        # Собираем контекст
        context = {
            **log_context.get(),
            **self._get_thread_context(),
            **extra
        }
        
        # Создаем запись
        record = LogRecord(
            timestamp=time.time(),
            level=level,
            scope=scope,
            message=message,
            module=module,
            extra=context
        )
        
        # Отправляем на запись
        if self.batcher:
            # Через батчер
            for channel in channels:
                self.batcher.add_message(channel, record.to_dict())
            self.stats['messages_batched'] += 1
        else:
            # Напрямую в диспетчер
            self.dispatcher.route_log(record, channels)
    
    def push_context(self, **context_vars):
        """Добавляет контекст для текущего потока"""
        with self._context_lock:
            current_context = self._get_thread_context()
            new_context = {**current_context, **context_vars}
            self._context_stack.append(new_context)
    
    def pop_context(self):
        """Убирает последний добавленный контекст"""
        with self._context_lock:
            if self._context_stack:
                self._context_stack.pop()
    
    def _get_thread_context(self) -> Dict[str, Any]:
        """Получает контекст для текущего потока"""
        with self._context_lock:
            return self._context_stack[-1] if self._context_stack else {}
    
    # Удобные методы для разных областей
    def system(self, level: LogLevel, message: str, module: str = "main", **extra):
        """Логирование системных событий"""
        self.log(LogScope.SYSTEM, level, message, module, **extra)
    
    def business(self, level: LogLevel, message: str, module: str = "main", **extra):
        """Логирование бизнес-логики"""
        self.log(LogScope.BUSINESS, level, message, module, **extra)
    
    def performance(self, level: LogLevel, message: str, module: str = "main", **extra):
        """Логирование производительности"""
        self.log(LogScope.PERFORMANCE, level, message, module, **extra)
    
    def audit(self, level: LogLevel, message: str, module: str = "main", **extra):
        """Логирование аудита"""
        self.log(LogScope.AUDIT, level, message, module, **extra)
    
    def security(self, level: LogLevel, message: str, module: str = "main", **extra):
        """Логирование безопасности"""
        self.log(LogScope.SECURITY, level, message, module, **extra)
    
    def debug(self, message: str, module: str = "main", **extra):
        """Отладочное логирование"""
        self.log(LogScope.DEBUG, LogLevel.DEBUG, message, module, **extra)
    
    def info(self, message: str, module: str = "main", **extra):
        """Информационное сообщение"""
        self.log(LogScope.BUSINESS, LogLevel.INFO, message, module, **extra)
    
    def warning(self, message: str, module: str = "main", **extra):
        """Предупреждение"""
        self.log(LogScope.SYSTEM, LogLevel.WARNING, message, module, **extra)
    
    def error(self, message: str, module: str = "main", **extra):
        """Ошибка"""
        self.log(LogScope.SYSTEM, LogLevel.ERROR, message, module, **extra)
    
    def critical(self, message: str, module: str = "main", **extra):
        """Критическая ошибка"""
        self.log(LogScope.SYSTEM, LogLevel.CRITICAL, message, module, **extra)
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику использования"""
        base_stats = {
            'app_name': self.app_name,
            'messages_processed': self.stats['messages_processed'],
            'messages_skipped': self.stats['messages_skipped'],
            'channels_count': len(self.channels),
            'batching_enabled': self.config.enable_batching
        }
        
        if self.batcher:
            base_stats.update({
                'messages_batched': self.stats['messages_batched'],
                'batch_stats': self.batcher.stats
            })
        
        return base_stats
    
    def flush(self):
        """Принудительно сбрасывает все буферизованные логи"""
        if self.batcher:
            self.batcher.flush_all()
    
    def shutdown(self):
        """Корректно останавливает систему логирования"""
        self.flush()


# Глобальные функции для удобства
def get_logger() -> Optional[LoggerManager]:
    """Возвращает глобальный экземпляр логгера"""
    return LoggerManager._instance

def init_logging(config: LogConfig) -> LoggerManager:
    """Инициализирует глобальную систему логирования"""
    return LoggerManager(config)

def shutdown_logging():
    """Останавливает систему логирования"""
    logger = get_logger()
    if logger:
        logger.shutdown()