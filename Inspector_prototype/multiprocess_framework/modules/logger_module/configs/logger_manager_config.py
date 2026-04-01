# -*- coding: utf-8 -*-
"""
LoggerManagerConfig — SchemaBase / ChannelRoutingConfig для LoggerManager.

Каналы, scopes и modules — отдельные сущности (как в прототипе managers_schema_lite).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import yaml
from pydantic import Field

from ...channel_routing_module import ChannelRoutingConfig
from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ..core.log_enums import LogLevel, LogScope

_STD_FMT = "%(asctime)s [%(levelname)s] [%(proc_name)s] %(name)s: %(message)s"
_FILE_MAX = 10 * 1024 * 1024

_LEVEL_ORDER = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class LoggerChannelSchema(SchemaBase):
    """Описание одного канала логирования."""

    name: str = ""
    type: str = "file"
    enabled: bool = True
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    max_size: int = 10 * 1024 * 1024
    backup_count: int = 5
    rotate: bool = True
    file_path: Optional[str] = None
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)


class LoggerScopeSchema(SchemaBase):
    """Скоуп логирования (ключи SYSTEM, BUSINESS, …)."""

    enabled: bool = True
    min_level: str = "INFO"
    channels: List[str] = Field(default_factory=list)
    modules: List[str] = Field(default_factory=list)

    def should_log(self, level: LogLevel, module: str) -> bool:
        if not self.enabled:
            return False
        try:
            lv = _LEVEL_ORDER.index(level.value)
            mv = _LEVEL_ORDER.index(self.min_level.upper())
        except ValueError:
            return True
        if lv < mv:
            return False
        if self.modules and module not in self.modules:
            return False
        return True


class LoggerModuleSchema(SchemaBase):
    """Per-module file logging (router_messages, processor, …)."""

    enabled: bool = True
    file_path: Optional[str] = None
    min_level: str = "DEBUG"
    max_size: Optional[int] = None
    backup_count: Optional[int] = None
    rotate: bool = True


def _default_channels() -> Dict[str, LoggerChannelSchema]:
    return {
        "system_file": LoggerChannelSchema(
            type="file",
            enabled=True,
            file_path="system.log",
            max_size=_FILE_MAX,
            backup_count=5,
            format=_STD_FMT,
        ),
        "messages_file": LoggerChannelSchema(
            type="file",
            enabled=True,
            file_path="messages.log",
            max_size=_FILE_MAX,
            backup_count=5,
            format=_STD_FMT,
        ),
        "console": LoggerChannelSchema(
            type="console",
            enabled=True,
            format=_STD_FMT,
        ),
    }


def _default_scopes(log_level: str = "INFO") -> Dict[str, LoggerScopeSchema]:
    return {
        "SYSTEM": LoggerScopeSchema(
            enabled=True,
            min_level="WARNING",
            channels=["console", "system_file"],
        ),
        "BUSINESS": LoggerScopeSchema(
            enabled=True,
            min_level=log_level,
            channels=["system_file", "messages_file"],
        ),
        "PERFORMANCE": LoggerScopeSchema(
            enabled=True,
            min_level="INFO",
            channels=["system_file"],
        ),
        "DEBUG": LoggerScopeSchema(
            enabled=True,
            min_level="DEBUG",
            channels=["system_file"],
        ),
    }


def _default_modules() -> Dict[str, LoggerModuleSchema]:
    return {
        "router_messages": LoggerModuleSchema(
            enabled=True,
            file_path="messages.log",
            min_level="DEBUG",
        ),
        "database": LoggerModuleSchema(
            enabled=True,
            file_path="database.log",
            min_level="INFO",
        ),
        "processor": LoggerModuleSchema(
            enabled=True,
            file_path="processor.log",
            min_level="INFO",
        ),
        "processor_frames": LoggerModuleSchema(
            enabled=True,
            file_path="frames.log",
            min_level="DEBUG",
            rotate=False,
        ),
        "camera": LoggerModuleSchema(
            enabled=True,
            file_path="camera.log",
            min_level="INFO",
        ),
        "renderer": LoggerModuleSchema(
            enabled=True,
            file_path="renderer.log",
            min_level="INFO",
        ),
        "robot": LoggerModuleSchema(
            enabled=True,
            file_path="robot.log",
            min_level="INFO",
        ),
        "gui": LoggerModuleSchema(
            enabled=True,
            file_path="gui.log",
            min_level="INFO",
        ),
    }


@register_schema("LoggerManagerConfig")
class LoggerManagerConfig(ChannelRoutingConfig):
    """Конфигурация LoggerManager: каналы, scopes, modules."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "LoggerManager"

    app_name: str = "unknown_app"
    default_level: str = "INFO"
    enable_batching: bool = True
    batch_size: int = 100
    batch_interval: float = 1.0

    channels: Annotated[
        Dict[str, LoggerChannelSchema],
        FieldMeta("Каналы: имя → параметры"),
    ] = Field(default_factory=_default_channels)

    scopes: Annotated[
        Dict[str, LoggerScopeSchema],
        FieldMeta("Скоупы: SYSTEM, BUSINESS, …"),
    ] = Field(default_factory=_default_scopes)

    modules: Annotated[
        Dict[str, LoggerModuleSchema],
        FieldMeta("Per-module файлы"),
    ] = Field(default_factory=_default_modules)

    def get_scope_config(self, scope: LogScope) -> LoggerScopeSchema:
        key = scope.name
        if key in self.scopes:
            return self.scopes[key]
        ch = list(self.channels.keys())[:1] if self.channels else []
        return LoggerScopeSchema(
            enabled=True,
            min_level=self.default_level,
            channels=ch,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoggerManagerConfig":
        if not data:
            return cls()
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, config_path: str) -> "LoggerManagerConfig":
        path = Path(config_path)
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls.model_validate(raw)
