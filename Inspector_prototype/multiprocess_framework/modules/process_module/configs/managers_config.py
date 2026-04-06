# -*- coding: utf-8 -*-
"""
ManagersConfig — корневая SchemaBase-сборка секций proc_dict['managers'].

Композиция конфигов модулей (logger, error, stats, router, command, console).
Эталонные экземпляры (blueprints) вверху файла — источник дефолтов через
``model_copy(deep=True)`` в ``default_factory``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar

from pydantic import Field

from ...command_module.configs.command_manager_config import CommandManagerConfig
from ...console_module.configs.console_config import ConsoleConfig
from ...data_schema_module import SchemaBase
from ...error_module.configs.error_manager_config import ErrorManagerConfig
from ...logger_module.configs.logger_manager_config import LoggerManagerConfig
from ...router_module.configs.router_manager_config import RouterManagerConfig
from ...statistics_module.configs.stats_config import StatsManagerConfig

# ---------------------------------------------------------------------------
# Blueprint defaults (копии через default_factory, без общей мутации)
# ---------------------------------------------------------------------------

_LOGGER_BLUEPRINT = LoggerManagerConfig(
    app_name="inspector",
    default_level="INFO",
    log_directory="logs",
)

_ERROR_BLUEPRINT = ErrorManagerConfig()

_STATS_BLUEPRINT = StatsManagerConfig()

_ROUTER_BLUEPRINT = RouterManagerConfig(
    duplicate_messages_to_logger=True,
)

_COMMAND_BLUEPRINT = CommandManagerConfig(
    enable_logging=True,
    enable_statistics=True,
)

_CONSOLE_BLUEPRINT = ConsoleConfig()


def _default_logger() -> LoggerManagerConfig:
    return _LOGGER_BLUEPRINT.model_copy(deep=True)


def _default_error() -> ErrorManagerConfig:
    return _ERROR_BLUEPRINT.model_copy(deep=True)


def _default_stats() -> StatsManagerConfig:
    return _STATS_BLUEPRINT.model_copy(deep=True)


def _default_router() -> RouterManagerConfig:
    return _ROUTER_BLUEPRINT.model_copy(deep=True)


def _default_command() -> CommandManagerConfig:
    return _COMMAND_BLUEPRINT.model_copy(deep=True)


def _default_console() -> ConsoleConfig:
    return _CONSOLE_BLUEPRINT.model_copy(deep=True)


TManagersConfig = TypeVar("TManagersConfig", bound="ManagersConfig")


class ManagersConfig(SchemaBase):
    """Корневая схема конфигурации менеджеров процесса."""

    log_dir: str = "logs"
    logger: LoggerManagerConfig = Field(default_factory=_default_logger)
    error: ErrorManagerConfig = Field(default_factory=_default_error)
    stats: StatsManagerConfig = Field(default_factory=_default_stats)
    router: RouterManagerConfig = Field(default_factory=_default_router)
    command: CommandManagerConfig = Field(default_factory=_default_command)
    console: ConsoleConfig = Field(default_factory=_default_console)

    def managers_for_proc_dict(self) -> Dict[str, Any]:
        """Секции proc_dict['managers'] без log_dir (Dict at Boundary)."""
        return managers_payload_for_proc(self)

    @classmethod
    def from_log_dir(
        cls: type[TManagersConfig],
        log_dir: str,
        log_level: Optional[str] = None,
    ) -> TManagersConfig:
        """Собрать конфиг: дефолты LoggerManagerConfig + log_directory и уровень BUSINESS = log_level."""
        return managers_from_log_dir(log_dir, log_level, model_cls=cls)


def managers_payload_for_proc(cfg: ManagersConfig) -> Dict[str, Any]:
    """Секции ``proc_dict['managers']`` без ``log_dir`` (Dict at Boundary)."""
    d = cfg.model_dump()
    d.pop("log_dir", None)
    return d


def managers_from_log_dir(
    log_dir: str,
    log_level: Optional[str] = None,
    *,
    model_cls: type[TManagersConfig] = ManagersConfig,
) -> TManagersConfig:
    """
    Собрать экземпляр корневой схемы менеджеров: логгер и error-секция под каталог логов.

    ``model_cls`` — подкласс :class:`ManagersConfig` (например прототипный lite), без дублирования тела фабрики.
    """
    level = (log_level or os.environ.get("INSPECTOR_LOG_LEVEL", "INFO")).upper()
    root = Path(log_dir).expanduser()
    if not root.is_absolute():
        root = (Path.cwd() / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    log_dir_s = str(root)

    base_logger = _LOGGER_BLUEPRINT.model_copy(
        update={
            "app_name": "inspector",
            "default_level": level,
            "log_directory": log_dir_s,
        }
    )
    scopes = dict(base_logger.scopes)
    if "BUSINESS" in scopes:
        scopes["BUSINESS"] = scopes["BUSINESS"].model_copy(update={"min_level": level})
    logger = base_logger.model_copy(update={"scopes": scopes})
    error = ErrorManagerConfig(
        error_file_path=os.path.join(log_dir_s, "errors.log"),
        critical_file_path=os.path.join(log_dir_s, "critical.log"),
        warnings_file_path=os.path.join(log_dir_s, "warnings.log"),
    )
    return model_cls(
        log_dir=log_dir,
        logger=logger,
        error=error,
        stats=_default_stats(),
        router=_default_router(),
        command=_default_command(),
        console=_default_console(),
    )
