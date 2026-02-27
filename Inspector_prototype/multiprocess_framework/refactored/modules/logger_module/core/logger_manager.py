"""
Основной менеджер логирования (Refactored).
Объединяет все компоненты в единую систему с поддержкой:
- Наследование от BaseManager
- Интеграция с ObservableMixin
- Динамическая конфигурация через ConfigManager
- Поддержка файлов по модулям
- Интеграция с RouterManager для межпроцессного логирования
"""
import time
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from contextvars import ContextVar
from pathlib import Path

if TYPE_CHECKING:
    from multiprocessing import Process

from ...base_manager import BaseManager, ObservableMixin
from ...base_manager.interfaces import IBaseManager
from ..interfaces import ILoggerManager
from .log_config import LogConfig, LogLevel, LogScope, ScopeConfig, ChannelConfig
from .log_dispatcher import LogDispatcher, LogRecord
from ..batcher.batch_manager import BatchManager, BatchConfig
from ..channels.log_channel import create_channel, LogChannel

# Глобальная переменная для контекста (поддерживает асинхронность)
log_context: ContextVar[Dict[str, Any]] = ContextVar('log_context', default={})


class LoggerManager(BaseManager, ObservableMixin, ILoggerManager):
    """
    Главный менеджер системы логирования (Refactored).
    
    Features:
    - Гибкая конфигурация через YAML и ConfigManager
    - Множественные каналы записи
    - Батчинг для производительности
    - Контекстное логирование
    - Фильтрация по областям и модулям
    - Поддержка отдельных файлов для каждого модуля
    - Динамическое изменение конфигурации в реальном времени
    - Интеграция с RouterManager для межпроцессного логирования
    """
    
    _instance = None
    
    def __init__(
        self,
        manager_name: str = "LoggerManager",
        process: Optional["Process"] = None,
        config: Optional[LogConfig] = None,
        config_manager: Optional[Any] = None,
        router_manager: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        enable_router_routing: bool = True,
        **kwargs
    ):
        """
        Инициализация менеджера логирования.
        
        Args:
            manager_name: Имя менеджера
            process: Ссылка на родительский процесс
            config: Конфигурация логирования (если None, создается дефолтная)
            config_manager: Менеджер конфигурации для динамического управления
            router_manager: RouterManager для межпроцессного логирования
            managers: Словарь других менеджеров для интеграции
            enable_router_routing: Включить маршрутизацию логов через RouterManager
            **kwargs: Дополнительные параметры для ObservableMixin
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Подготовка менеджеров для ObservableMixin
        if managers is None:
            managers = {}
        
        if router_manager:
            managers['router'] = router_manager
        
        config_dict = kwargs.get('config', {})
        config_dict['router_routing'] = enable_router_routing
        
        # Инициализация ObservableMixin
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config_dict,
            auto_proxy=True
        )
        
        # Сохраняем зависимости
        self._config_manager = config_manager
        self._router_manager = router_manager
        
        # Инициализация конфигурации
        self.config = config or LogConfig()
        self.app_name = self.config.app_name
        
        # Инициализация компонентов
        self.dispatcher = LogDispatcher(app_name=self.config.app_name, process=process)
        self.batcher = None
        self.channels: Dict[str, LogChannel] = {}
        self._module_channels: Dict[str, LogChannel] = {}  # Каналы для отдельных модулей
        
        # Контекст логирования (используем contextvars вместо блокировок)
        self._context_stack: List[Dict[str, Any]] = []
        
        # Кэш для быстрых проверок (сбрасывается при изменении конфига)
        self._decision_cache: Dict[str, bool] = {}
        self._cache_enabled = True
        
        # Статистика
        self.stats = {
            'messages_processed': 0,
            'messages_skipped': 0,
            'messages_batched': 0,
            'messages_routed': 0,
            'module_files_created': 0
        }
        
        # Настройка системы
        self._setup_channels()
        self._setup_batcher()
        
        # Сохраняем инстанс для глобального доступа
        LoggerManager._instance = self
    
    def initialize(self) -> bool:
        """
        Инициализация менеджера логирования.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Инициализация диспетчера
            self.dispatcher.initialize()
            
            self.is_initialized = True
            self.info("LoggerManager initialized", module="logger_manager")
            return True
        except Exception as e:
            self._fallback_log("ERROR", f"LoggerManager initialization failed: {e}")
            return False
    
    def shutdown(self) -> bool:
        """
        Корректное завершение работы менеджера.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            self.info("LoggerManager shutting down", module="logger_manager")
            self.flush()
            
            # Закрываем диспетчер
            self.dispatcher.shutdown()
            
            # Закрываем все каналы
            for channel in list(self.channels.values()) + list(self._module_channels.values()):
                if hasattr(channel, 'close'):
                    try:
                        channel.close()
                    except Exception:
                        pass
            
            self.is_initialized = False
            return True
        except Exception as e:
            self._fallback_log("ERROR", f"LoggerManager shutdown failed: {e}")
            return False
    
    def _setup_channels(self):
        """Настраивает каналы записи"""
        for channel_name, channel_config in self.config.channels.items():
            if channel_config.enabled:
                self._setup_channel(channel_name, channel_config)
    
    def _setup_channel(self, channel_name: str, channel_config: ChannelConfig):
        """Настраивает один канал."""
        try:
            channel = create_channel(channel_config)
            self.channels[channel_name] = channel
            
            # Регистрируем обработчик в диспетчере
            self.dispatcher.register_channel_handler(
                channel_name,
                channel.write
            )
        except Exception as e:
            self._fallback_log("ERROR", f"Failed to setup channel {channel_name}: {e}")
    
    def _setup_module_channel(self, module_name: str, file_path: Optional[str] = None):
        """
        Настраивает отдельный канал для модуля.
        
        Args:
            module_name: Имя модуля
            file_path: Путь к файлу (если None, используется logs/{module_name}.log)
        """
        if not file_path:
            file_path = f"logs/{module_name}.log"
        
        try:
            # Создаем конфигурацию канала для модуля
            channel_config = ChannelConfig(
                name=f"module_{module_name}",
                type="file",
                enabled=True,
                file_path=file_path,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                max_size=10 * 1024 * 1024,  # 10MB
                backup_count=5
            )
            
            channel = create_channel(channel_config)
            self._module_channels[module_name] = channel
            
            # Регистрируем обработчик
            self.dispatcher.register_channel_handler(
                f"module_{module_name}",
                channel.write
            )
            
            self.stats['module_files_created'] += 1
            self.debug(f"Module channel created: {module_name} -> {file_path}", module="logger_manager")
        except Exception as e:
            self._fallback_log("ERROR", f"Failed to setup module channel {module_name}: {e}")
    
    def _setup_batcher(self):
        """Настраивает батчинг если включен"""
        if self.config.enable_batching:
            batch_config = BatchConfig(
                max_size=self.config.batch_size,
                flush_interval=self.config.batch_interval
            )
            self.batcher = BatchManager(self._flush_batch, batch_config)
        else:
            self.batcher = None
    
    def _flush_batch(self, channel: str, batch: List[Dict]):
        """Обрабатывает пачку логов"""
        for record_dict in batch:
            # Восстанавливаем LogRecord из словаря
            record = LogRecord(
                timestamp=record_dict['timestamp'],
                level=LogLevel[record_dict['level']],
                scope=LogScope[record_dict['scope']],
                message=record_dict['message'],
                module=record_dict['module'],
                extra=record_dict.get('extra', {})
            )
            self.dispatcher.route_log(record, [channel])
    
    def should_log(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        """
        Определяет, нужно ли логировать сообщение.
        Использует кэш для производительности.
        """
        if not self._cache_enabled:
            return self._should_log_direct(scope, level, module)
        
        cache_key = f"{scope.value}:{level.value}:{module}"
        
        if cache_key in self._decision_cache:
            return self._decision_cache[cache_key]
        
        should_log = self._should_log_direct(scope, level, module)
        self._decision_cache[cache_key] = should_log
        return should_log
    
    def _should_log_direct(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        """Прямая проверка без кэша."""
        scope_config = self.config.get_scope_config(scope)
        return scope_config.should_log(level, module)
    
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
        
        # Проверяем наличие отдельного канала для модуля
        if module in self._module_channels:
            channels.append(f"module_{module}")
        
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
        
        # Маршрутизация через RouterManager (если включена)
        if self.is_enabled('router_routing') and self._router_manager:
            self._route_via_router(record)
        
        # Отправляем на запись
        if self.batcher:
            # Через батчер
            for channel in channels:
                self.batcher.add_message(channel, record.to_dict())
            self.stats['messages_batched'] += 1
        else:
            # Напрямую в диспетчер
            self.dispatcher.route_log(record, channels)
    
    def _route_via_router(self, record: LogRecord):
        """
        Маршрутизирует лог через RouterManager для межпроцессного логирования.
        
        Args:
            record: Запись лога
        """
        try:
            if not self._router_manager:
                return
            
            # Конвертируем LogLevel в строку
            level_str = record.level.value.lower()
            
            # Отправляем через роутер
            self._router_manager.send({
                'channel': 'logger',
                'text': record.message,
                'level': level_str.upper(),
                'timestamp': True,
                'process': self.manager_name,
                'module': record.module,
                'scope': record.scope.value,
                'extra': record.extra
            })
            
            self.stats['messages_routed'] += 1
        except Exception as e:
            # Не логируем ошибку через себя, чтобы избежать рекурсии
            pass
    
    def push_context(self, **context_vars):
        """Добавляет контекст для текущего потока"""
        current_context = self._get_thread_context()
        new_context = {**current_context, **context_vars}
        self._context_stack.append(new_context)
    
    def pop_context(self):
        """Убирает последний добавленный контекст"""
        if self._context_stack:
            self._context_stack.pop()
    
    def _get_thread_context(self) -> Dict[str, Any]:
        """Получает контекст для текущего потока"""
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
    
    # Методы для управления модулями
    def enable_module_logging(self, module_name: str, file_path: Optional[str] = None):
        """
        Включает отдельное логирование для модуля.
        
        Args:
            module_name: Имя модуля
            file_path: Путь к файлу (опционально)
        """
        self._setup_module_channel(module_name, file_path)
    
    def disable_module_logging(self, module_name: str):
        """
        Выключает логирование для модуля.
        
        Args:
            module_name: Имя модуля
        """
        if module_name in self._module_channels:
            channel = self._module_channels[module_name]
            if hasattr(channel, 'close'):
                channel.close()
            del self._module_channels[module_name]
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику использования"""
        base_stats = {
            'app_name': self.app_name,
            'messages_processed': self.stats['messages_processed'],
            'messages_skipped': self.stats['messages_skipped'],
            'messages_routed': self.stats['messages_routed'],
            'channels_count': len(self.channels),
            'module_channels_count': len(self._module_channels),
            'module_files_created': self.stats['module_files_created'],
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
    
    def _fallback_log(self, level: str, message: str, module: str = "system"):
        """Аварийное логирование при недоступности основных методов."""
        try:
            print(f"[{level}] [{module}] {message}")
        except Exception:
            pass


# Глобальные функции для удобства
def get_logger() -> Optional[LoggerManager]:
    """Возвращает глобальный экземпляр логгера"""
    return LoggerManager._instance

def init_logging(config: LogConfig, **kwargs) -> LoggerManager:
    """Инициализирует глобальную систему логирования"""
    return LoggerManager(config=config, **kwargs)

def shutdown_logging():
    """Останавливает систему логирования"""
    logger = get_logger()
    if logger:
        logger.shutdown()

