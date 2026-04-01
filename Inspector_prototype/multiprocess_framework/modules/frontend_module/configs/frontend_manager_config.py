# -*- coding: utf-8 -*-
"""FrontendManagerConfig — схема FrontendManager с вложенными подменеджерами."""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from data_schema_module import FieldMeta, SchemaBase, register_schema

from .thread_manager_config import ThreadManagerConfig
from .window_manager_config import WindowManagerConfig


@register_schema("frontend_manager")
class FrontendManagerConfig(SchemaBase):
    """Плоский корень + ссылки на схемы window/thread."""

    manager_name: Annotated[str, FieldMeta("Имя менеджера")] = "FrontendManager"
    connection_map: Annotated[Dict[str, str], FieldMeta("Сопоставление каналов")] = Field(
        default_factory=dict
    )
    window: Annotated[
        WindowManagerConfig,
        FieldMeta("Параметры WindowManager"),
    ] = Field(default_factory=WindowManagerConfig)
    thread: Annotated[
        ThreadManagerConfig,
        FieldMeta("Параметры ThreadManager"),
    ] = Field(default_factory=ThreadManagerConfig)
    hot_reload_enabled: Annotated[bool, FieldMeta("Подписка на изменения конфига")] = True
    registers_bridge_cache: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Кэш моста регистров (опционально)"),
    ] = None
