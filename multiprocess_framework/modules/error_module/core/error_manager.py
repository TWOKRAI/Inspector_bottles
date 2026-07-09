# -*- coding: utf-8 -*-
"""
ErrorManager — брат LoggerManager (общий предок LoggerCore) с severity-based routing.

Task 5.14 (CRM-развязка): ErrorManager наследует общий лог-слой ``LoggerCore``,
а НЕ ``LoggerManager`` (композиция общего слоя вместо IS-A). Оба — потомки
``LoggerCore`` → ``ChannelRoutingManager``.

Ключевые улучшения (Фаза 3 — CRM унификация):
  - _setup_level_routes() строит _level_to_channel: {level_str → channel_name}
    и регистрирует маршруты в self._dispatcher (из CRM) напрямую.
  - log() перегружает LoggerCore.log() для WARNING/ERROR/CRITICAL:
    → ищет channel_name через _level_to_channel (O(1))
    → пишет через buffer (если есть) или напрямую в channel
  - DEBUG/INFO → fallback на LoggerCore.log() (scope-based)
  - Результат: level routing теперь РЕАЛЬНО используется, не просто регистрируется.

Архитектурная аналогия:
  RouterManager:   message → channel_dispatcher(key=type) → IMessageChannel
  ErrorManager:    error   → _level_to_channel(key=level) → ILogChannel
"""

import time
import traceback
from typing import Optional, Any, Union, Dict

from ...logger_module.core.log_config import LoggerManagerConfig, LogLevel, LogScope
from ...logger_module.core.log_types import LogRecord
from ...logger_module.core.logger_core import LoggerCore
from ..configs.error_manager_config import ErrorManagerConfig
from ..interfaces import IErrorManager
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
        f"config must be dict, LoggerManagerConfig, ErrorManagerConfig, or object"
        f" with build() -> (name, dict), got {type(config)}"
    )


class ErrorManager(LoggerCore, IErrorManager):
    """Менеджер ошибок с severity-based channel routing.

    Task 5.14: брат ``LoggerManager`` (оба — потомки ``LoggerCore``), а НЕ его
    наследник (композиция общего лог-слоя вместо IS-A). Общий слой берётся из
    ``LoggerCore``; специфика severity-routing добавляется здесь.

    Добавляет поверх LoggerCore:
      1. _level_to_channel: Dict[str, str] — прямой маппинг уровня → канал.
         WARNING → warnings_file, ERROR → errors_file, CRITICAL → critical_file.

      2. log() override — для WARNING/ERROR/CRITICAL использует _level_to_channel
         вместо scope-based routing. DEBUG/INFO идут через LoggerCore.log().
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
        managers: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> None:
        resolved_name, log_config, include_stacktrace = _normalize_error_config(config)
        manager_name = resolved_name

        # Guard до super(): LoggerCore.__init__ дёргает self.log()/self.info() косвенно
        # (напр. _setup_module_channel → self.debug()), а переопределённый ErrorManager.log()
        # читает self._level_to_channel. Инициализируем его ДО super(), иначе AttributeError.
        # (Task 5.14: ErrorManager — брат LoggerManager через LoggerCore, singleton _instance
        #  живёт только на LoggerManager и здесь НЕ выставляется.)
        self._level_to_channel: Dict[str, str] = {}
        self._include_stacktrace = include_stacktrace

        super().__init__(
            manager_name=manager_name,
            process=process,
            config=log_config,
            config_manager=config_manager,
            managers=managers or {},
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

    def _rebuild_from_config(self, config: Dict[str, Any]) -> None:
        """Хук CRM.reconfigure: пересобрать каналы + перестроить severity-routing.

        Специфика ErrorManager поверх LoggerCore:
          - конфиг проходит через ``_normalize_error_config`` (принимает и плоский
            error-dict, и развёрнутый LoggerManagerConfig);
          - обновляется ``self._include_stacktrace``;
          - переиспользуется пересборка каналов родителя
            (``_apply_log_config_rebuild``), а затем перестраивается
            ``_level_to_channel`` через ``_setup_level_routes()`` — иначе
            severity-маршруты ссылались бы на закрытые каналы.
        """
        _name, log_config, include_stacktrace = _normalize_error_config(config)
        self._include_stacktrace = include_stacktrace
        self._apply_log_config_rebuild(log_config)
        self._setup_level_routes()

    def log(
        self,
        scope: LogScope,
        level: LogLevel,
        message: str,
        module: str = "main",
        **extra,
    ) -> None:
        """Override: WARNING/ERROR/CRITICAL → level-based routing.

        DEBUG/INFO → fallback to LoggerCore.log() (scope-based).

        Теперь level routing РЕАЛЬНО используется (в старом коде маршруты
        были зарегистрированы но route_by_level() никогда не вызывался).
        """
        self.stats["messages_processed"] += 1

        channel_name = self._level_to_channel.get(level.value)
        if channel_name is None:
            # DEBUG / INFO / unknown level → parent scope-based routing
            # Don't double-count messages_processed
            self.stats["messages_processed"] -= 1
            return LoggerCore.log(self, scope, level, message, module, **extra)

        record_dict = LogRecord(
            timestamp=time.time(),
            level=level,
            scope=scope,
            message=message,
            module=module,
            extra={**self._get_thread_context(), **extra},
        ).to_dict()

        # Tail логов (Task 1.5): severity-путь ErrorManager не зовёт super().log(),
        # поэтому tap'ы кормим здесь явно (DEBUG/INFO уходят в LoggerCore.log выше).
        if self._tap_sinks:
            self._emit_to_taps(record_dict, level)

        if self._buffer is not None:
            self._buffer.enqueue(channel_name, record_dict)
            self.stats["messages_batched"] += 1
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
        """Статистика ErrorManager — расширяет LoggerCore.get_stats()."""
        stats = super().get_stats()
        stats["include_stacktrace"] = self._include_stacktrace
        stats["level_routes"] = dict(self._level_to_channel)
        return stats
