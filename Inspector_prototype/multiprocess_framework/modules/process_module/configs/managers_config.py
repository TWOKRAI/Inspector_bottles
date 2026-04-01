# -*- coding: utf-8 -*-
"""
ManagersConfig — корневая SchemaBase-сборка секций proc_dict['managers'].

Композиция конфигов модулей (logger, error, stats, router, command, console).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from pydantic import Field

from ...console_module.configs.console_config import ConsoleConfig
from ...data_schema_module import SchemaBase
from ...error_module.configs.error_manager_config import ErrorManagerConfig
from ...logger_module.configs.logger_manager_config import LoggerManagerConfig
from ...statistics_module.configs.stats_config import StatsManagerConfig


class RouterManagersSection(SchemaBase):
    """Параметры RouterManager, задаваемые через managers['router']."""

    duplicate_messages_to_logger: bool = True


class CommandManagersSection(SchemaBase):
    """Параметры CommandManager (managers['command'])."""

    enable_logging: bool = True
    enable_statistics: bool = True


class ManagersConfig(SchemaBase):
    """Корневая схема конфигурации менеджеров процесса."""

    log_dir: str = "logs"
    logger: LoggerManagerConfig = Field(default_factory=LoggerManagerConfig)
    error: ErrorManagerConfig = Field(default_factory=ErrorManagerConfig)
    stats: StatsManagerConfig = Field(default_factory=StatsManagerConfig)
    router: RouterManagersSection = Field(default_factory=RouterManagersSection)
    command: CommandManagersSection = Field(default_factory=CommandManagersSection)
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)

    def managers_for_proc_dict(self) -> Dict[str, Any]:
        """Секции proc_dict['managers'] без log_dir (Dict at Boundary)."""
        d = self.model_dump()
        d.pop("log_dir", None)
        return d

    @classmethod
    def from_log_dir(
        cls,
        log_dir: str,
        log_level: Optional[str] = None,
    ) -> "ManagersConfig":
        """Собрать конфиг с путями файлов внутри log_dir (как в app_config)."""
        level = (log_level or os.environ.get("INSPECTOR_LOG_LEVEL", "INFO")).upper()
        os.makedirs(log_dir, exist_ok=True)
        _fmt = "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s"
        _max = 10 * 1024 * 1024

        logger_dict: Dict[str, Any] = {
            "app_name": "inspector",
            "default_level": level,
            "enable_batching": True,
            "batch_size": 100,
            "batch_interval": 1.0,
            "channels": {
                "system_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "system.log"),
                    "max_size": _max,
                    "backup_count": 5,
                    "format": _fmt,
                },
                "messages_file": {
                    "type": "file",
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "messages.log"),
                    "max_size": _max,
                    "backup_count": 5,
                    "format": _fmt,
                },
                "console": {
                    "type": "console",
                    "enabled": True,
                    "format": _fmt,
                },
            },
            "scopes": {
                "SYSTEM": {
                    "enabled": True,
                    "min_level": "WARNING",
                    "channels": ["console", "system_file"],
                },
                "BUSINESS": {
                    "enabled": True,
                    "min_level": level,
                    "channels": ["system_file", "messages_file"],
                },
                "PERFORMANCE": {
                    "enabled": True,
                    "min_level": "INFO",
                    "channels": ["system_file"],
                },
                "DEBUG": {
                    "enabled": True,
                    "min_level": "DEBUG",
                    "channels": ["system_file"],
                },
            },
            "modules": {
                "router_messages": {
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "messages.log"),
                    "min_level": "DEBUG",
                },
                "database": {
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "database.log"),
                    "min_level": "INFO",
                },
                "processor": {
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "processor.log"),
                    "min_level": "INFO",
                },
                "processor_frames": {
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "frames.log"),
                    "min_level": "DEBUG",
                    "rotate": False,
                },
                "camera": {
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "camera.log"),
                    "min_level": "INFO",
                },
                "renderer": {
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "renderer.log"),
                    "min_level": "INFO",
                },
                "robot": {
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "robot.log"),
                    "min_level": "INFO",
                },
                "gui": {
                    "enabled": True,
                    "file_path": os.path.join(log_dir, "gui.log"),
                    "min_level": "INFO",
                },
            },
        }
        logger = LoggerManagerConfig.model_validate(logger_dict)
        error = ErrorManagerConfig(
            error_file_path=os.path.join(log_dir, "errors.log"),
            critical_file_path=os.path.join(log_dir, "critical.log"),
            warnings_file_path=os.path.join(log_dir, "warnings.log"),
        )
        stats = StatsManagerConfig()
        router = RouterManagersSection()
        command = CommandManagersSection()
        console = ConsoleConfig()
        return cls(
            log_dir=log_dir,
            logger=logger,
            error=error,
            stats=stats,
            router=router,
            command=command,
            console=console,
        )
