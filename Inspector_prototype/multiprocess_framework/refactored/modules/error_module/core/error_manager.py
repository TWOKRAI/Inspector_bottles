"""
ErrorManager — специализированный менеджер ошибок (наследник LoggerManager).

Dict at boundary: принимает dict, LogConfig, или объект с build() -> (name, dict).
Без зависимости от data_schema_module в core — только logger_module.
"""

import traceback
from typing import Optional, Any, Union, Dict

from ...logger_module import LoggerManager
from ...logger_module.core.log_config import LogConfig


# Дефолтный конфиг (dict) — без зависимости от ErrorManagerConfig
_DEFAULT_CONFIG: Dict[str, Any] = {
    "app_name": "errors",
    "default_level": "ERROR",
    "enable_batching": True,
    "batch_size": 50,
    "batch_interval": 0.5,
    "channels": {
        "errors_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/errors.log",
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "max_size": 10 * 1024 * 1024,
            "backup_count": 5,
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
    """
    Менеджер ошибок — наследник LoggerManager.

    Специализация: default_level=ERROR, отдельный файл errors.log.
    Принимает config как dict (dict at boundary) или объект с build().
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
        Инициализация ErrorManager.

        Args:
            config: dict, LogConfig, или объект с build() -> (name, dict).
                    None — дефолтный конфиг для ошибок.
            enable_router_routing: по умолчанию False для error-менеджера.
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

    def log_exception(
        self,
        exc: BaseException,
        message: str = "",
        module: str = "errors",
        include_stacktrace: Optional[bool] = None,
    ) -> None:
        """
        Логировать исключение с опциональным traceback.

        Args:
            exc: Исключение
            message: Дополнительное сообщение
            module: Модуль-источник
            include_stacktrace: Переопределить self._include_stacktrace
        """
        full_message = f"{message}: {exc}" if message else str(exc)
        if include_stacktrace if include_stacktrace is not None else self._include_stacktrace:
            full_message += f"\n{traceback.format_exc()}"

        self.error(full_message, module=module)
