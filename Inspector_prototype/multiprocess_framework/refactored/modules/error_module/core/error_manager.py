# -*- coding: utf-8 -*-
"""
ErrorManager — специализированный менеджер ошибок (наследник LoggerManager).

Добавляет поверх LoggerManager:
  - Severity-based channel routing:
      CRITICAL → critical.log
      ERROR    → errors.log
      WARNING  → warnings.log (если настроен)
  - log_exception() с форматированием traceback
  - Дефолтный конфиг ERROR-уровня

Dict at boundary: принимает dict, LogConfig, или объект с build() -> (name, dict).
Без зависимости от data_schema_module в core — только logger_module.

Архитектурная аналогия с RouterManager:
  RouterManager:   message → channel_dispatcher(key=type) → IMessageChannel
  ErrorManager:    error   → level_dispatcher(key=level)  → ILogChannel
"""

import traceback
from typing import Optional, Any, Union, Dict

from ...logger_module import LoggerManager
from ...logger_module.core.log_config import LogConfig
from ...logger_module.core.log_dispatcher import LogDispatcher


# Дефолтный конфиг (dict) — без зависимости от ErrorManagerConfig.
# Три канала по уровням серьёзности — ERROR-менеджер отделяет warning от fatal.
_DEFAULT_CONFIG: Dict[str, Any] = {
    "app_name": "errors",
    "default_level": "WARNING",   # Ловим WARNING, ERROR, CRITICAL
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


def _normalize_config(
    config: Optional[Union[Dict[str, Any], LogConfig, Any]],
) -> tuple[str, LogConfig, bool]:
    """
    Преобразовать config в (manager_name, LogConfig, include_stacktrace).

    - dict -> LogConfig.from_dict(config)
    - LogConfig -> как есть
    - объект с build() -> build() возвращает (name, dict)
    - None -> дефолтный dict
    """
    manager_name = "ErrorManager"
    include_stacktrace = True

    if config is None:
        return manager_name, LogConfig.from_dict(_DEFAULT_CONFIG), include_stacktrace

    if isinstance(config, LogConfig):
        return manager_name, config, include_stacktrace

    if isinstance(config, dict):
        include_stacktrace = config.get("include_stacktrace", True)
        return manager_name, LogConfig.from_dict(config), include_stacktrace

    if hasattr(config, "build") and callable(config.build):
        name, config_dict = config.build()
        manager_name = name
        include_stacktrace = config_dict.get("include_stacktrace", True)
        if hasattr(config, "include_stacktrace"):
            include_stacktrace = config.include_stacktrace
        return manager_name, LogConfig.from_dict(config_dict), include_stacktrace

    raise TypeError(
        f"config must be dict, LogConfig, or object with build() -> (name, dict), got {type(config)}"
    )


class ErrorManager(LoggerManager):
    """Менеджер ошибок — специализированный наследник LoggerManager.

    Добавляет поверх LoggerManager:
      1. Severity-based channel routing через LogDispatcher.register_level_route():
           CRITICAL → critical.log
           ERROR    → errors.log
           WARNING  → warnings.log
         Аналог channel_dispatcher в RouterManager — маршрутизация по ключу level.

      2. log_exception() — логирование исключения с traceback.

      3. Дефолтный конфиг с тремя severity-каналами.

    Жизненный цикл:
        em = ErrorManager()                     # дефолтный конфиг
        em = ErrorManager(config=my_dict)       # dict at boundary
        em = ErrorManager(config=ErrorManagerConfig(...))  # RegisterBase
        em.initialize()
        em.log_exception(exc, "context", module="my_module")
        em.shutdown()

    Интеграция через ObservableMixin:
        ObservableMixin.__init__(self, managers={'errors': error_manager})
        self._track_error(exc, context={"method": "process"})
    """

    def __init__(
        self,
        manager_name: str = "ErrorManager",
        process: Optional[Any] = None,
        config: Optional[Union[Dict[str, Any], LogConfig, Any]] = None,
        config_manager: Optional[Any] = None,
        router_manager: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        enable_router_routing: bool = False,
        **kwargs,
    ) -> None:
        """
        Args:
            manager_name:          Имя менеджера.
            process:               Родительский процесс (опционально).
            config:                dict, LogConfig, объект с build(), или None (дефолт).
            config_manager:        ConfigManager (опционально).
            router_manager:        RouterManager для межпроцессных логов (опционально).
            managers:              Словарь дополнительных менеджеров для ObservableMixin.
            enable_router_routing: False по умолчанию — ошибки пишутся локально.
        """
        resolved_name, log_config, include_stacktrace = _normalize_config(config)
        manager_name = resolved_name

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

        self._include_stacktrace = include_stacktrace

    def initialize(self) -> bool:
        """Инициализация ErrorManager.

        Вызывает LoggerManager.initialize(), затем настраивает level-based routing.

        Returns:
            True при успехе.
        """
        result = super().initialize()
        if result:
            self._setup_level_routes()
        return result

    def _setup_level_routes(self) -> None:
        """Настроить level-based routing через LogDispatcher.

        Регистрирует каналы в LogDispatcher.register_level_route() по уровню серьёзности.
        После этого можно использовать dispatcher.route_by_level(record) вместо route_log().

        Маппинг (если канал существует в конфиге):
          CRITICAL → critical_file
          ERROR    → errors_file  (также CRITICAL, если нет critical_file)
          WARNING  → warnings_file (также WARNING идёт в errors_file если нет warnings_file)
        """
        d: LogDispatcher = self.dispatcher

        has_critical = "critical_file" in self.channels
        has_errors = "errors_file" in self.channels
        has_warnings = "warnings_file" in self.channels

        # CRITICAL
        if has_critical:
            d.register_level_route("CRITICAL", "critical_file", self.channels["critical_file"].write)
        elif has_errors:
            d.register_level_route("CRITICAL", "errors_file", self.channels["errors_file"].write)

        # ERROR
        if has_errors:
            d.register_level_route("ERROR", "errors_file", self.channels["errors_file"].write)

        # WARNING
        if has_warnings:
            d.register_level_route("WARNING", "warnings_file", self.channels["warnings_file"].write)
        elif has_errors:
            d.register_level_route("WARNING", "errors_file", self.channels["errors_file"].write)

    def log_exception(
        self,
        exc: BaseException,
        message: str = "",
        module: str = "errors",
        include_stacktrace: Optional[bool] = None,
    ) -> None:
        """Логировать исключение с опциональным traceback.

        Args:
            exc:               Объект исключения.
            message:           Дополнительное контекстное сообщение.
            module:            Модуль-источник исключения.
            include_stacktrace: True/False переопределяет глобальный флаг.
                               None → использует значение из конфига.

        Example:
            try:
                risky_operation()
            except ValueError as e:
                error_manager.log_exception(
                    e, "invalid input data", module="validator"
                )
        """
        full_message = f"{message}: {exc}" if message else str(exc)
        use_trace = include_stacktrace if include_stacktrace is not None else self._include_stacktrace
        if use_trace:
            tb = traceback.format_exc()
            if tb and tb.strip() != "NoneType: None":
                full_message += f"\n{tb}"

        self.error(full_message, module=module)

    def get_stats(self) -> Dict[str, Any]:
        """Статистика ErrorManager — расширяет LoggerManager.get_stats()."""
        stats = super().get_stats()
        stats["include_stacktrace"] = self._include_stacktrace
        stats["level_routes"] = self.dispatcher.get_level_routes()
        return stats
