"""
Основной менеджер логирования.
Объединяет все компоненты в единую систему с поддержкой:
- Наследование от BaseManager
- Интеграция с ObservableMixin
- Динамическая конфигурация через ConfigManager
- Поддержка файлов по модулям
- Интеграция с Message_module
"""

import time
from typing import Dict, List, Any, Optional
from contextvars import ContextVar
from pathlib import Path

from ..Base_manager_module.base_manager import BaseManager
from ..Base_manager_module.observable_mixin import ObservableMixin
from ..Config_module import ConfigManager

from .config import LogConfig, LogLevel, LogScope, ScopeConfig, ChannelConfig
from .dispatcher import LogDispatcher, LogRecord
from .batcher import BatchManager, BatchConfig
from .channels import create_channel, LogChannel

# Глобальная переменная для контекста (поддерживает асинхронность)
log_context: ContextVar[Dict[str, Any]] = ContextVar('log_context', default={})


class LoggerManager(BaseManager, ObservableMixin):
    """
    Главный менеджер системы логирования.
    
    Features:
    - Гибкая конфигурация через YAML и ConfigManager
    - Множественные каналы записи
    - Батчинг для производительности
    - Контекстное логирование
    - Фильтрация по областям и модулям
    - Поддержка отдельных файлов для каждого модуля
    - Динамическое изменение конфигурации в реальном времени
    - Интеграция с Message_module для межпроцессного логирования
    """
    
    _instance = None
    
    def __init__(
        self,
        config: Optional[LogConfig] = None,
        process: Optional[Any] = None,
        config_manager: Optional[ConfigManager] = None,
        managers: Optional[Dict[str, Any]] = None,
        enable_message_routing: bool = True
    ):
        """
        Инициализация менеджера логирования.
        
        Args:
            config: Конфигурация логирования (если None, создается дефолтная)
            process: Ссылка на родительский процесс
            config_manager: Менеджер конфигурации для динамического управления
            managers: Словарь других менеджеров для интеграции
            enable_message_routing: Включить маршрутизацию логов через Message_module
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, "LoggerManager", process)
        
        # Инициализация ObservableMixin
        ObservableMixin.__init__(
            self,
            managers=managers or {},
            config={'message_routing': enable_message_routing}
        )
        
        # Сохраняем config_manager для динамической конфигурации
        self._config_manager = config_manager
        
        # Инициализация конфигурации
        self.config = config or LogConfig()
        self.app_name = self.config.app_name
        
        # Инициализация компонентов
        self.dispatcher = LogDispatcher(app_name=self.config.app_name)
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
        
        # Настройка подписки на изменения конфигурации
        if self._config_manager:
            # ConfigManager может быть либо экземпляром ConfigManager, либо Config
            # Если это ConfigManager, получаем Config через get_instance('logging')
            # Если это Config, используем напрямую
            if isinstance(self._config_manager, ConfigManager):
                # Получаем или создаем конфигурацию логирования
                config = ConfigManager.get_instance('logging')
                # Подписываемся на все изменения логирования
                config.subscribe(self._on_config_changed, key='logging.*')
            elif hasattr(self._config_manager, 'subscribe'):
                # Это Config объект - подписываемся на изменения логирования
                self._config_manager.subscribe(self._on_config_changed, key='logging.*')
            
            self._load_config_from_manager()
        
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
    
    def _load_config_from_manager(self):
        """Загружает конфигурацию из ConfigManager если доступна."""
        if not self._config_manager:
            return
        
        try:
            # ConfigManager может быть либо экземпляром ConfigManager, либо Config
            # Если это ConfigManager, получаем Config через get_instance('logging')
            # Если это Config, используем напрямую
            if isinstance(self._config_manager, ConfigManager):
                # Получаем или создаем конфигурацию логирования
                config = ConfigManager.get_instance('logging')
                log_config = config.get('logging', {})
            elif hasattr(self._config_manager, 'get'):
                # Это Config объект
                log_config = self._config_manager.get('logging', {})
            else:
                log_config = {}
            
            if log_config:
                self._apply_dynamic_config(log_config)
        except Exception as e:
            self._fallback_log("WARNING", f"Failed to load config from ConfigManager: {e}")
    
    def _on_config_changed(self, config_key: str, old_value: Any, new_value: Any):
        """
        Обработчик изменения конфигурации в реальном времени.
        
        Args:
            config_key: Ключ конфигурации (может быть вложенным через точку)
            old_value: Старое значение (не используется, но требуется для совместимости с subscribe)
            new_value: Новое значение
        """
        if not config_key.startswith('logging.'):
            return
        
        try:
            # Удаляем префикс 'logging.'
            key = config_key[8:]  # len('logging.') = 8
            
            # Применяем изменение (без блокировок для multiprocessing)
            if key == 'enable_batching':
                self.config.enable_batching = bool(new_value)
                self._setup_batcher()
            elif key == 'batch_size':
                self.config.batch_size = int(new_value)
            elif key == 'batch_interval':
                self.config.batch_interval = float(new_value)
                if self.batcher:
                    self.batcher.config.flush_interval = float(new_value)
            elif key.startswith('scopes.'):
                # Изменение конфигурации области
                scope_key = key[7:]  # len('scopes.') = 7
                self._update_scope_config(scope_key, new_value)
            elif key.startswith('channels.'):
                # Изменение конфигурации канала
                channel_key = key[9:]  # len('channels.') = 9
                self._update_channel_config(channel_key, new_value)
            elif key.startswith('modules.'):
                # Включение/выключение логирования для модуля
                module_key = key[8:]  # len('modules.') = 8
                self._update_module_config(module_key, new_value)
            
            # Сбрасываем кэш решений
            self._decision_cache.clear()
            
            self.debug(f"Config updated: {config_key} = {new_value}", module="logger_manager")
        except Exception as e:
            self._fallback_log("ERROR", f"Failed to apply config change {config_key}: {e}")
    
    def _update_scope_config(self, scope_key: str, value: Any):
        """Обновляет конфигурацию области логирования."""
        try:
            # Формат: scope_name.enabled или scope_name.min_level
            parts = scope_key.split('.', 1)
            if len(parts) != 2:
                return
            
            scope_name, field = parts
            scope = LogScope[scope_name.upper()]
            
            if scope not in self.config.scopes:
                return
            
            scope_config = self.config.scopes[scope]
            if field == 'enabled':
                scope_config.enabled = bool(value)
            elif field == 'min_level':
                scope_config.min_level = LogLevel[value.upper()]
        except (KeyError, ValueError, AttributeError):
            pass
    
    def _update_channel_config(self, channel_key: str, value: Any):
        """Обновляет конфигурацию канала."""
        try:
            # Формат: channel_name.enabled
            parts = channel_key.split('.', 1)
            if len(parts) != 2:
                return
            
            channel_name, field = parts
            if channel_name not in self.config.channels:
                return
            
            channel_config = self.config.channels[channel_name]
            if field == 'enabled':
                channel_config.enabled = bool(value)
                if value:
                    # Включаем канал если его нет
                    if channel_name not in self.channels:
                        self._setup_channel(channel_name, channel_config)
                else:
                    # Выключаем канал
                    if channel_name in self.channels:
                        del self.channels[channel_name]
        except (KeyError, ValueError, AttributeError):
            pass
    
    def _update_module_config(self, module_key: str, value: Any):
        """Обновляет конфигурацию модуля."""
        # Формат: module_name.enabled или module_name.file_path
        parts = module_key.split('.', 1)
        if len(parts) != 2:
            return
        
        module_name, field = parts
        
        if field == 'enabled':
            # Включаем/выключаем логирование для модуля
            # Обновляем все области
            for scope_config in self.config.scopes.values():
                if isinstance(value, bool):
                    if value:
                        scope_config.modules.discard(module_name)  # Убираем из исключений
                    else:
                        scope_config.modules.add(module_name)  # Добавляем в исключения
        elif field == 'file_path':
            # Изменяем путь к файлу для модуля
            self._setup_module_channel(module_name, str(value))
    
    def _apply_dynamic_config(self, config: Dict[str, Any]):
        """Применяет динамическую конфигурацию из словаря."""
        # Обновляем базовые настройки (без блокировок для multiprocessing)
        if 'enable_batching' in config:
            self.config.enable_batching = bool(config['enable_batching'])
            self._setup_batcher()
        
        if 'batch_size' in config:
            self.config.batch_size = int(config['batch_size'])
        
        if 'batch_interval' in config:
            self.config.batch_interval = float(config['batch_interval'])
        
        # Обновляем области
        if 'scopes' in config:
            for scope_name, scope_data in config['scopes'].items():
                try:
                    scope = LogScope[scope_name.upper()]
                    if scope in self.config.scopes:
                        scope_config = self.config.scopes[scope]
                        if 'enabled' in scope_data:
                            scope_config.enabled = bool(scope_data['enabled'])
                        if 'min_level' in scope_data:
                            scope_config.min_level = LogLevel[scope_data['min_level'].upper()]
                except (KeyError, ValueError):
                    pass
        
        # Обновляем каналы
        if 'channels' in config:
            for channel_name, channel_data in config['channels'].items():
                if channel_name in self.config.channels:
                    channel_config = self.config.channels[channel_name]
                    if 'enabled' in channel_data:
                        channel_config.enabled = bool(channel_data['enabled'])
                        if channel_config.enabled and channel_name not in self.channels:
                            self._setup_channel(channel_name, channel_config)
                        elif not channel_config.enabled and channel_name in self.channels:
                            del self.channels[channel_name]
        
        # Сбрасываем кэш
        self._decision_cache.clear()
    
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
        
        # Маршрутизация через Message_module (если включена)
        if self.is_enabled('message_routing') and self.has_manager('message'):
            self._route_via_message(record)
        
        # Отправляем на запись
        if self.batcher:
            # Через батчер
            for channel in channels:
                self.batcher.add_message(channel, record.to_dict())
            self.stats['messages_batched'] += 1
        else:
            # Напрямую в диспетчер
            self.dispatcher.route_log(record, channels)
    
    def _route_via_message(self, record: LogRecord):
        """
        Маршрутизирует лог через Message_module для межпроцессного логирования.
        
        Args:
            record: Запись лога
        """
        try:
            message_manager = self.get_manager('message')
            if not message_manager:
                return
            
            # Конвертируем LogLevel в формат Message_module
            level_mapping = {
                LogLevel.DEBUG: 'debug',
                LogLevel.INFO: 'info',
                LogLevel.WARNING: 'warning',
                LogLevel.ERROR: 'error',
                LogLevel.CRITICAL: 'critical'
            }
            
            level_str = level_mapping.get(record.level, 'info')
            
            # Создаем сообщение через Message_module
            from ..Message_module import Message, MessageType
            
            log_message = Message.create(
                type=MessageType.LOG,
                sender=self.manager_name,
                targets=["logger"],
                level=level_str,
                message=record.message,
                module=record.module
            )
            
            # Добавляем дополнительный контекст в metadata
            if record.extra:
                log_message.set_metadata(record.extra)
            
            # Отправляем через роутер процесса (если доступен)
            if self.process and hasattr(self.process, 'router'):
                self.process.router.send(log_message.to_dict())
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
        
        # Обновляем конфигурацию через ConfigManager если доступен
        if self._config_manager:
            self._config_manager.set(f"logging.modules.{module_name}.enabled", True)
            if file_path:
                self._config_manager.set(f"logging.modules.{module_name}.file_path", file_path)
    
    def disable_module_logging(self, module_name: str):
        """
        Выключает логирование для модуля.
        
        Args:
            module_name: Имя модуля
        """
        if module_name in self._module_channels:
            del self._module_channels[module_name]
        
        # Обновляем конфигурацию
        if self._config_manager:
            self._config_manager.set(f"logging.modules.{module_name}.enabled", False)
    
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
        
        # Добавляем статистику BaseManager
        base_stats.update(super().get_stats())
        
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
    return LoggerManager(config, **kwargs)

def shutdown_logging():
    """Останавливает систему логирования"""
    logger = get_logger()
    if logger:
        logger.shutdown()
