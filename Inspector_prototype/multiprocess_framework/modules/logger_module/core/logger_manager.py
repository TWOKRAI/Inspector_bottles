# -*- coding: utf-8 -*-
"""
LoggerManager (Refactored) — наследник ChannelRoutingManager.

Миграция Фаза 2:
  - Наследует ChannelRoutingManager вместо BaseManager + ObservableMixin
  - Каналы хранятся в self._channel_registry (thread-safe, из CRM)
  - Батчинг через self._buffer (BatchBuffer из CRM)
  - LogDispatcher сохранён для backward compat (ErrorManager, Фаза 3)
  - Публичный API не изменён (info, error, log, flush, get_stats и т.д.)
"""
import time
from typing import Dict, List, Any, Optional, TYPE_CHECKING
from contextvars import ContextVar
from pathlib import Path

if TYPE_CHECKING:
    from multiprocessing import Process

from ...channel_routing_module import ChannelRoutingManager
from ...channel_routing_module.buffers.batch_buffer import BatchBuffer, BatchConfig as CRMBatchConfig
from ..interfaces import ILoggerManager
from ..configs.logger_manager_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerModuleSchema,
)
from .log_config import LogLevel, LogScope
from .log_dispatcher import LogDispatcher, LogRecord
from ..channels.log_channel import create_channel, LogChannel

log_context: ContextVar[Dict[str, Any]] = ContextVar('log_context', default={})


class LoggerManager(ChannelRoutingManager, ILoggerManager):
    """
    Менеджер системы логирования (наследует ChannelRoutingManager).

    Использует от ChannelRoutingManager:
      - self._channel_registry  — thread-safe хранилище каналов (IChannel)
      - self._buffer            — BatchBuffer для пакетной записи
      - self._dispatcher        — Dispatcher (базовый, для level-based routing в ErrorManager)

    Сохраняет свою специфику:
      - LoggerManagerConfig    — конфигурация областей/уровней/каналов (SchemaBase)
      - LogDispatcher          — channel-based routing (ErrorManager)
      - Scope-based routing    — log() определяет каналы по LoggerScopeSchema
      - Module channels        — отдельный файл для каждого модуля
      - Context stack          — push_context / pop_context
    """

    _instance = None

    def __init__(
        self,
        manager_name: str = "LoggerManager",
        process: Optional["Process"] = None,
        config: Optional[Any] = None,
        config_manager: Optional[Any] = None,
        router_manager: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        enable_router_routing: bool = True,
        **kwargs,
    ):
        if managers is None:
            managers = {}
        if router_manager:
            managers['router'] = router_manager

        observable_config = {'router_routing': enable_router_routing}

        # --- Normalize config ---
        log_config = self._resolve_log_config(config)

        # --- Init ChannelRoutingManager (without buffer — set up later) ---
        ChannelRoutingManager.__init__(
            self,
            manager_name=manager_name,
            process=process,
            config=None,
            buffer_strategy=None,
            dispatcher_key_field="level",
            managers=managers,
            observable_config=observable_config,
            auto_proxy=kwargs.get('auto_proxy', True),
        )

        self._config_manager = config_manager
        self._router_manager = router_manager

        self.config = log_config
        self.app_name = log_config.app_name

        # LogDispatcher — backward compat for ErrorManager (Phase 3 will remove)
        self.dispatcher = LogDispatcher(app_name=self.config.app_name, process=process)

        # Module-specific channels (separate from main registry)
        self._module_channels: Dict[str, LogChannel] = {}

        self._context_stack: List[Dict[str, Any]] = []

        self._decision_cache: Dict[str, bool] = {}
        self._cache_enabled = True

        self.stats = {
            'messages_processed': 0,
            'messages_skipped': 0,
            'messages_batched': 0,
            'messages_routed': 0,
            'module_files_created': 0,
        }

        self._setup_channels()
        self._setup_batcher()

        LoggerManager._instance = self

    # =========================================================================
    # ЖИЗНЕННЫЙ ЦИКЛ
    # =========================================================================

    def initialize(self) -> bool:
        try:
            self.dispatcher.initialize()
            self._dispatcher.initialize()
            if self._buffer:
                self._buffer.start()
            self.is_initialized = True
            self.info("LoggerManager initialized", module="logger_manager")
            return True
        except Exception as e:
            self._fallback_log("ERROR", f"LoggerManager initialization failed: {e}")
            return False

    def shutdown(self) -> bool:
        try:
            self.info("LoggerManager shutting down", module="logger_manager")
            self.flush()
            if self._buffer:
                self._buffer.stop()
            self.dispatcher.shutdown()
            self._dispatcher.shutdown()

            for channel in self._channel_registry.clear():
                try:
                    channel.close()
                except Exception:
                    pass
            for channel in list(self._module_channels.values()):
                try:
                    channel.close()
                except Exception:
                    pass

            self.is_initialized = False
            return True
        except Exception as e:
            self._fallback_log("ERROR", f"LoggerManager shutdown failed: {e}")
            return False

    # =========================================================================
    # SETUP
    # =========================================================================

    @staticmethod
    def _resolve_log_config(config: Any) -> LoggerManagerConfig:
        """Convert config (None | dict | LoggerManagerConfig | build()) to LoggerManagerConfig."""
        if config is None:
            return LoggerManagerConfig()
        if isinstance(config, LoggerManagerConfig):
            return config
        if isinstance(config, dict):
            return LoggerManagerConfig.from_dict(config)
        if hasattr(config, "build") and callable(config.build):
            result = config.build()
            if isinstance(result, tuple) and len(result) == 2:
                _, cfg_dict = result
                if isinstance(cfg_dict, dict):
                    return LoggerManagerConfig.from_dict(cfg_dict)
                return LoggerManagerConfig()
            if isinstance(result, dict):
                return LoggerManagerConfig.from_dict(result)
        return LoggerManagerConfig()

    def _setup_channels(self):
        """Создать каналы из конфига и зарегистрировать в CRM registry.

        - channels: основные каналы (system_file, messages_file, console)
        - modules: отдельные файлы для модулей (database, processor, frames и т.д.)
        """
        for channel_name, channel_config in self.config.channels.items():
            if channel_config.enabled:
                self._setup_channel(str(channel_name), channel_config)

        # Автосоздание каналов для модулей из config.modules
        for module_name, module_config in self.config.modules.items():
            if getattr(module_config, 'enabled', True) and getattr(
                module_config, 'file_path', None
            ):
                self._setup_module_channel(module_name, module_config)

    def _setup_channel(self, channel_name: str, channel_config: LoggerChannelSchema):
        try:
            channel = create_channel(channel_name, channel_config)
            self._channel_registry.register(channel)
            self.dispatcher.register_channel_handler(channel_name, channel.write)
        except Exception as e:
            self._fallback_log("ERROR", f"Failed to setup channel {channel_name}: {e}")

    def _setup_module_channel(self, module_name: str, module_config: LoggerModuleSchema):
        """Создать файловый канал для module_* (из modules или enable_module_logging)."""
        path = module_config.file_path or f"logs/{module_name}.log"
        max_size = (
            module_config.max_size
            if module_config.max_size is not None
            else 10 * 1024 * 1024
        )
        backup_count = (
            module_config.backup_count
            if module_config.backup_count is not None
            else 5
        )
        rotate = module_config.rotate
        try:
            ch_name = f"module_{module_name}"
            channel_config = LoggerChannelSchema(
                name=ch_name,
                type="file",
                enabled=True,
                file_path=str(path),
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                max_size=max_size,
                backup_count=backup_count,
                rotate=rotate,
            )
            channel = create_channel(ch_name, channel_config)
            self._module_channels[module_name] = channel
            self._channel_registry.register(channel)
            self.dispatcher.register_channel_handler(
                f"module_{module_name}", channel.write
            )
            self.stats['module_files_created'] += 1
            self.debug(
                f"Module channel created: {module_name} -> {path}",
                module="logger_manager",
            )
        except Exception as e:
            self._fallback_log("ERROR", f"Failed to setup module channel {module_name}: {e}")

    def _setup_batcher(self):
        """Настроить BatchBuffer из CRM если батчинг включён."""
        if self.config.enable_batching:
            self._buffer = BatchBuffer(
                flush_fn=self._flush_batch,
                config=CRMBatchConfig(
                    max_size=self.config.batch_size,
                    flush_interval=self.config.batch_interval,
                ),
            )
        else:
            self._buffer = None

    def _flush_batch(self, channel: str, batch: List[Dict]):
        """Callback для BatchBuffer — записать пачку в канал."""
        ch = self._channel_registry.get(channel)
        if ch is not None:
            for record_dict in batch:
                try:
                    ch.write(record_dict)
                except Exception:
                    pass
            return

        ch = self._module_channels.get(channel.replace("module_", "", 1))
        if ch is not None:
            for record_dict in batch:
                try:
                    ch.write(record_dict)
                except Exception:
                    pass

    # =========================================================================
    # ОСНОВНОЙ API ЛОГИРОВАНИЯ
    # =========================================================================

    def should_log(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        if not self._cache_enabled:
            return self._should_log_direct(scope, level, module)
        cache_key = f"{scope.value}:{level.value}:{module}"
        if cache_key in self._decision_cache:
            return self._decision_cache[cache_key]
        result = self._should_log_direct(scope, level, module)
        self._decision_cache[cache_key] = result
        return result

    def _should_log_direct(self, scope: LogScope, level: LogLevel, module: str) -> bool:
        scope_config = self.config.get_scope_config(scope)
        return scope_config.should_log(level, module)

    def log(
        self,
        scope: LogScope,
        level: LogLevel,
        message: str,
        module: str = "main",
        **extra,
    ):
        self.stats['messages_processed'] += 1

        if not self.should_log(scope, level, module):
            self.stats['messages_skipped'] += 1
            return

        scope_config = self.config.get_scope_config(scope)
        channels = scope_config.channels or self._channel_registry.names()

        if module in self._module_channels:
            channels = list(channels)
            channels.append(f"module_{module}")

        context = {
            **log_context.get(),
            **self._get_thread_context(),
            **extra,
        }

        record = LogRecord(
            timestamp=time.time(),
            level=level,
            scope=scope,
            message=message,
            module=module,
            extra=context,
        )

        if self.is_enabled('router_routing') and self._router_manager:
            self._route_via_router(record)

        if self._buffer:
            for ch_name in channels:
                self._buffer.enqueue(ch_name, record.to_dict())
            self.stats['messages_batched'] += 1
        else:
            self._write_record_to_channels(record, channels)

    def _write_record_to_channels(self, record: LogRecord, channel_names: List[str]) -> None:
        """Write log record directly to named channels (no buffer)."""
        record_dict = record.to_dict()
        for ch_name in channel_names:
            ch = self._channel_registry.get(ch_name)
            if ch is None:
                ch = self._module_channels.get(ch_name.replace("module_", "", 1))
            if ch is not None:
                try:
                    ch.write(record_dict)
                except Exception:
                    pass
            else:
                handler = self.dispatcher.channel_handlers.get(ch_name)
                if handler:
                    try:
                        handler(record_dict)
                    except Exception:
                        pass

    def _route_via_router(self, record: LogRecord) -> None:
        if not self._router_manager:
            return
        try:
            from ....message_module import Message, MessageType

            msg = Message.create(
                MessageType.LOG,
                sender=self.manager_name,
                targets=["logger"],
                level=record.level.value.lower(),
                message=record.message,
                module=record.module,
            )
            if record.extra:
                msg.add_metadata("scope", record.scope.value)
                msg.add_metadata("extra", record.extra)

            self._router_manager.send(msg)
            self.stats['messages_routed'] += 1
        except Exception:
            pass

    # =========================================================================
    # КОНТЕКСТ
    # =========================================================================

    def push_context(self, **context_vars):
        current_context = self._get_thread_context()
        new_context = {**current_context, **context_vars}
        self._context_stack.append(new_context)

    def pop_context(self):
        if self._context_stack:
            self._context_stack.pop()

    def _get_thread_context(self) -> Dict[str, Any]:
        return self._context_stack[-1] if self._context_stack else {}

    # =========================================================================
    # УДОБНЫЕ МЕТОДЫ ПО ОБЛАСТИ
    # =========================================================================

    def system(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.SYSTEM, level, message, module, **extra)

    def business(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.BUSINESS, level, message, module, **extra)

    def performance(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.PERFORMANCE, level, message, module, **extra)

    def audit(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.AUDIT, level, message, module, **extra)

    def security(self, level: LogLevel, message: str, module: str = "main", **extra):
        self.log(LogScope.SECURITY, level, message, module, **extra)

    # =========================================================================
    # УДОБНЫЕ МЕТОДЫ ПО УРОВНЮ
    # =========================================================================

    def debug(self, message: str, module: str = "main", **extra):
        self.log(LogScope.DEBUG, LogLevel.DEBUG, message, module, **extra)

    def info(self, message: str, module: str = "main", **extra):
        self.log(LogScope.BUSINESS, LogLevel.INFO, message, module, **extra)

    def warning(self, message: str, module: str = "main", **extra):
        self.log(LogScope.SYSTEM, LogLevel.WARNING, message, module, **extra)

    def error(self, message: str, module: str = "main", **extra):
        self.log(LogScope.SYSTEM, LogLevel.ERROR, message, module, **extra)

    def critical(self, message: str, module: str = "main", **extra):
        self.log(LogScope.SYSTEM, LogLevel.CRITICAL, message, module, **extra)

    # =========================================================================
    # УПРАВЛЕНИЕ МОДУЛЯМИ
    # =========================================================================

    def enable_module_logging(self, module_name: str, file_path: Optional[str] = None):
        self._setup_module_channel(
            module_name, LoggerModuleSchema(enabled=True, file_path=file_path)
        )

    def disable_module_logging(self, module_name: str):
        if module_name in self._module_channels:
            channel = self._module_channels[module_name]
            try:
                channel.close()
            except Exception:
                pass
            self._channel_registry.unregister(f"module_{module_name}")
            del self._module_channels[module_name]

    # =========================================================================
    # BACKWARD COMPAT: self.channels (property)
    # =========================================================================

    @property
    def channels(self) -> Dict[str, Any]:
        """Backward compat: {channel_name: channel_object}.

        Used by ErrorManager._setup_level_routes() to access channels by name.
        """
        return {ch.name: ch for ch in self._channel_registry.all()}

    @property
    def batcher(self):
        """Backward compat: alias for self._buffer."""
        return self._buffer

    # =========================================================================
    # СТАТИСТИКА
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        base_stats = {
            'app_name': self.app_name,
            'messages_processed': self.stats['messages_processed'],
            'messages_skipped': self.stats['messages_skipped'],
            'messages_routed': self.stats['messages_routed'],
            'channels_count': len(self._channel_registry),
            'module_channels_count': len(self._module_channels),
            'module_files_created': self.stats['module_files_created'],
            'batching_enabled': self.config.enable_batching,
        }

        if self._buffer:
            base_stats.update({
                'messages_batched': self.stats['messages_batched'],
                'batch_stats': self._buffer.stats,
            })

        return base_stats

    # =========================================================================
    # БУФЕР
    # =========================================================================

    def flush(self):
        if self._buffer:
            self._buffer.flush()

    # =========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ
    # =========================================================================

    def _fallback_log(self, level: str, message: str, module: str = "system"):
        try:
            print(f"[{level}] [{module}] {message}")
        except Exception:
            pass


# =========================================================================
# Глобальные функции
# =========================================================================

def get_logger() -> Optional[LoggerManager]:
    return LoggerManager._instance


def init_logging(config: LoggerManagerConfig, **kwargs) -> LoggerManager:
    return LoggerManager(config=config, **kwargs)


def shutdown_logging():
    logger = get_logger()
    if logger:
        logger.shutdown()
