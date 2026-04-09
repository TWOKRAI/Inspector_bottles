# -*- coding: utf-8 -*-
"""
ErrorManager — специализированный наследник LoggerManager с severity-based routing.

Ключевые улучшения (Фаза 3 — CRM унификация):
  - _setup_level_routes() строит _level_to_channel: {level_str → channel_name}
    и регистрирует маршруты в self._dispatcher (из CRM) напрямую.
  - log() перегружает LoggerManager.log() для WARNING/ERROR/CRITICAL:
    → ищет channel_name через _level_to_channel (O(1))
    → пишет через buffer (если есть) или напрямую в channel
  - DEBUG/INFO → fallback на LoggerManager.log() (scope-based)
  - Результат: level routing теперь РЕАЛЬНО используется, не просто регистрируется.

Архитектурная аналогия:
  RouterManager:   message → channel_dispatcher(key=type) → IMessageChannel
  ErrorManager:    error   → _level_to_channel(key=level) → ILogChannel
"""
import time
import traceback
from typing import Optional, Any, Union, Dict

from ...logger_module import LoggerManager
from ...logger_module.core.log_config import LoggerManagerConfig, LogLevel, LogScope
from ...logger_module.core.log_types import LogRecord
from ..configs.error_manager_config import ErrorManagerConfig
from .error_config_assembly import expand_error_manager_config


_DEFAULT_CONFIG: Dict[str, Any] = {
    "app_name": "errors",
    "default_level": "WARNING",
    "enable_batching": True,
    "batch_size": 50,
    "batch_interval": 0.5,
    "channels": {
        "critical_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/critical.log",
            "format": "%(asctime)s [CRITICAL] %(name)s: %(message)s",
            "max_size": 10 * 1024 * 1024,
            "backup_count": 10,
        },
        "errors_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/errors.log",
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "max_size": 10 * 1024 * 1024,
            "backup_count": 5,
        },
        "warnings_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/warnings.log",
            "format": "%(asctime)s [WARNING] %(name)s: %(message)s",
            "max_size": 5 * 1024 * 1024,
            "backup_count": 3,
        },
    },
}


def _normalize_error_config(
    config: Optional[Union[Dict[str, Any], LoggerManagerConfig, Any]],
) -> tuple[str, LoggerManagerConfig, bool]:
    """Преобразовать config → (manager_name, LoggerManagerConfig, include_stacktrace).

    Поддерживает: None | dict | ErrorManagerConfig | LoggerManagerConfig | build() → (name, dict).
    Плоские dict / ErrorManagerConfig проходят через :func:`expand_error_manager_config`.
    Вызывает TypeError для неизвестных типов.
    """
    manager_name = "ErrorManager"
    include_stacktrace = True

    if config is None:
        return manager_name, LoggerManagerConfig.model_validate(_DEFAULT_CONFIG), include_stacktrace

    if isinstance(config, LoggerManagerConfig):
        return manager_name, config, include_stacktrace

    if isinstance(config, ErrorManagerConfig):
        raw = config.model_dump()
        d = expand_error_manager_config(raw)
        manager_name = str(raw.get("manager_name", "ErrorManager"))
        include_stacktrace = bool(d.get("include_stacktrace", True))
        return manager_name, LoggerManagerConfig.model_validate(d), include_stacktrace

    if isinstance(config, dict):
        d = expand_error_manager_config(dict(config))
        include_stacktrace = bool(d.get("include_stacktrace", True))
        manager_name = str(d.get("manager_name", "ErrorManager"))
        return manager_name, LoggerManagerConfig.model_validate(d), include_stacktrace

    if hasattr(config, "build") and callable(config.build):
        name, config_dict = config.build()
        manager_name = name
        d = dict(config_dict) if isinstance(config_dict, dict) else {}
        include_stacktrace = d.get("include_stacktrace", True)
        if hasattr(config, "include_stacktrace"):
            include_stacktrace = bool(config.include_stacktrace)
        d = expand_error_manager_config(d)
        return manager_name, LoggerManagerConfig.model_validate(d), include_stacktrace

    raise TypeError(
        f"config must be dict, LoggerManagerConfig, ErrorManagerConfig, or object with build() -> (name, dict), got {type(config)}"
    )


class ErrorManager(LoggerManager):
    """Менеджер ошибок с severity-based channel routing.

    Добавляет поверх LoggerManager:
      1. _level_to_channel: Dict[str, str] — прямой маппинг уровня → канал.
         WARNING → warnings_file, ERROR → errors_file, CRITICAL → critical_file.

      2. log() override — для WARNING/ERROR/CRITICAL использует _level_to_channel
         вместо scope-based routing. DEBUG/INFO идут через LoggerManager.log().
         Buffer-aware: если _buffer задан → enqueue, иначе прямой write().

      3. log_exception() — traceback + self.error().

    Жизненный цикл:
        em = ErrorManager()
        em = ErrorManager(config={"app_name": "my_app"})
        em = ErrorManager(config=ErrorManagerConfig(...))
        em.initialize()
        em.log_exception(exc, "context", module="my_module")
        em.shutdown()
    """

    def __init__(
        self,
        manager_name: str = "ErrorManager",
        process: Optional[Any] = None,
        config: Optional[Union[Dict[str, Any], LoggerManagerConfig, Any]] = None,
        config_manager: Optional[Any] = None,
        router_manager: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        enable_router_routing: bool = False,
        **kwargs,
    ) -> None:
        resolved_name, log_config, include_stacktrace = _normalize_error_config(config)
        manager_name = resolved_name

        # До super(): LoggerManager.__init__ в конце выставляет LoggerManager._instance = self.
        # Если self — ErrorManager, до строки ниже у подкласса ещё нет _level_to_channel,
        # а косвенные вызовы (get_logger().error/…) приводят к AttributeError в log().
        self._level_to_channel: Dict[str, str] = {}
        self._include_stacktrace = include_stacktrace

        super().__init__(
            manager_name=manager_name,
            process=process,
            config=log_config,
            config_manager=config_manager,
            router_manager=router_manager,
            managers=managers or {},
            enable_router_routing=enable_router_routing,
            **kwargs,
        )

    def initialize(self) -> bool:
        result = super().initialize()
        if result:
            self._setup_level_routes()
        return result

    def _setup_level_routes(self) -> None:
        """Построить _level_to_channel: {уровень → имя канала}.

        После этого self._level_to_channel["ERROR"] == "errors_file" (O(1) в log()).
        """
        self._level_to_channel = {}

        has_critical = self._channel_registry.get("critical_file") is not None
        has_errors = self._channel_registry.get("errors_file") is not None
        has_warnings = self._channel_registry.get("warnings_file") is not None

        if has_critical:
            self._level_to_channel["CRITICAL"] = "critical_file"
        elif has_errors:
            self._level_to_channel["CRITICAL"] = "errors_file"

        if has_errors:
            self._level_to_channel["ERROR"] = "errors_file"

        if has_warnings:
            self._level_to_channel["WARNING"] = "warnings_file"
        elif has_errors:
            self._level_to_channel["WARNING"] = "errors_file"

    def log(
        self,
        scope: LogScope,
        level: LogLevel,
        message: str,
        module: str = "main",
        **extra,
    ) -> None:
        """Override: WARNING/ERROR/CRITICAL → level-based routing.

        DEBUG/INFO → fallback to LoggerManager.log() (scope-based).

        Теперь level routing РЕАЛЬНО используется (в старом коде маршруты
        были зарегистрированы но route_by_level() никогда не вызывался).
        """
        self.stats['messages_processed'] += 1

        channel_name = self._level_to_channel.get(level.value)
        if channel_name is None:
            # DEBUG / INFO / unknown level → parent scope-based routing
            # Don't double-count messages_processed
            self.stats['messages_processed'] -= 1
            return LoggerManager.log(self, scope, level, message, module, **extra)

        record_dict = LogRecord(
            timestamp=time.time(),
            level=level,
            scope=scope,
            message=message,
            module=module,
            extra={**self._get_thread_context(), **extra},
        ).to_dict()

        if self._buffer is not None:
            self._buffer.enqueue(channel_name, record_dict)
            self.stats['messages_batched'] += 1
        else:
            ch = self._channel_registry.get(channel_name)
            if ch is not None:
                try:
                    ch.write(record_dict)
                except Exception as e:
                    self._fallback_log("ERROR", f"write to {channel_name} failed: {e}")

    def log_exception(
        self,
        exc: BaseException,
        message: str = "",
        module: str = "errors",
        include_stacktrace: Optional[bool] = None,
    ) -> None:
        """Логировать исключение с traceback.

        Args:
            exc:               Объект исключения.
            message:           Дополнительный контекст.
            module:            Модуль-источник.
            include_stacktrace: Переопределить глобальный флаг (None → из конфига).
        """
        full_message = f"{message}: {exc}" if message else str(exc)
        use_trace = include_stacktrace if include_stacktrace is not None else self._include_stacktrace
        if use_trace:
            tb = traceback.format_exc()
            if tb and tb.strip() != "NoneType: None":
                full_message += f"\n{tb}"

        self.error(full_message, module=module)

    def track_error(
        self,
        error: BaseException,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Интеграция с ObservableMixin._track_error. Логирует через log_exception."""
        ctx = context or {}
        message = ctx.get("message", ctx.get("context", ""))
        if isinstance(message, dict):
            message = str(message)
        module = ctx.get("module", "unknown")
        self.log_exception(error, message=message or "", module=module)

    def get_stats(self) -> Dict[str, Any]:
        """Статистика ErrorManager — расширяет LoggerManager.get_stats()."""
        stats = super().get_stats()
        stats["include_stacktrace"] = self._include_stacktrace
        stats["level_routes"] = dict(self._level_to_channel)
        return stats
