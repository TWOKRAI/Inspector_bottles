# -*- coding: utf-8 -*-
"""
LoggerManagerConfig — SchemaBase / ChannelRoutingConfig для LoggerManager.

Каналы, scopes и modules — отдельные сущности (как в прототипе managers_schema_lite).
"""

from __future__ import annotations

from typing import Annotated, Dict, List, Optional

from pydantic import Field

from ...channel_routing_module import ChannelRoutingConfig
from ...data_schema_module import FieldMeta, SchemaBase, register_schema
from ..log_enums import LogLevel

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
    min_level: str = _LEVEL_ORDER[1]  # INFO
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


@register_schema("LoggerManagerConfig")
class LoggerManagerConfig(ChannelRoutingConfig):
    """Конфигурация LoggerManager: каналы, scopes, modules."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "LoggerManager"

    app_name: str = "unknown_app"
    default_level: str = "INFO"
    log_directory: Annotated[
        Optional[str],
        FieldMeta(
            "Корень для относительных file_path каналов и modules. "
            "None — каталог из MULTIPROCESS_LOG_DIR / INSPECTOR_LOG_DIR или системный temp "
            "(не текущий каталог пакета)."
        ),
    ] = None
    enable_batching: bool = True
    batch_size: int = 100
    batch_interval: float = 1.0

    modules: Annotated[
        Dict[str, LoggerModuleSchema],
        FieldMeta("Per-module файлы"),
    ] = {
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
        # trace — отдельный файл для диагностики cross-layer цепочек.
        # Логи с module="trace" уходят сюда (плюс в scope-каналы:
        # system_file/messages_file/console).
        "trace": LoggerModuleSchema(
            enabled=True,
            file_path="trace.log",
            min_level="DEBUG",
        ),
    }

    channels: Annotated[
        Dict[str, LoggerChannelSchema],
        FieldMeta("Каналы: имя → параметры"),
    ] = {
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

    scopes: Annotated[
        Dict[str, LoggerScopeSchema],
        FieldMeta("Скоупы: SYSTEM, BUSINESS, …"),
    ] = {
        "SYSTEM": LoggerScopeSchema(
            enabled=True,
            min_level="WARNING",
            channels=["console", "system_file"],
        ),
        "BUSINESS": LoggerScopeSchema(
            enabled=True,
            min_level=_LEVEL_ORDER[1],
            # console добавлен в BUSINESS — все INFO видны в stdout
            # (раньше там был только WARNING+ через SYSTEM scope).
            # Для production можно убрать console и оставить только файлы.
            channels=["system_file", "messages_file", "console"],
        ),
        "PERFORMANCE": LoggerScopeSchema(
            enabled=True,
            min_level=_LEVEL_ORDER[1],
            channels=["system_file"],
        ),
        "DEBUG": LoggerScopeSchema(
            enabled=True,
            min_level="DEBUG",
            channels=["system_file"],
        ),
    }
